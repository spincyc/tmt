"""Containment: tmt never writes or copies outside the repository.

A symlink is not a licence to leave. Every write path (init, new, agents
--write, vendor) resolves its target first and refuses one that lands
outside the repository root, and the registry save is atomic.

Atomic is not serialized, so the mutation lock is tested here too: two
processes that each load, mutate, and save must not lose one another's
work, and a process that cannot get the lock must fail rather than hang.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from _support import (
    SRC_DIR,
    TmtTestCase,
    git_init_commit,
    load_registry,
    run_git,
    run_tmt,
    save_registry,
    write_executable,
)

PLANT_STALE_STAGE = "open(f'.tmt.json.{os.getpid()}.tmt-tmp', 'w').close()"
RESTRICTIVE_UMASK = "os.umask(0o077)"

CONCURRENT_WORKERS = 6

# A dismiss stalled in its own window: it reads every record, filters,
# and rewrites the file, and a note appended between the read and the
# write used to be erased.
SLOW_DISMISS = """
import sys, time
from pathlib import Path
from tmt import notestore
root, reading = Path(sys.argv[1]), Path(sys.argv[2])
read_records = notestore._read
def stall(target):
    records = read_records(target)
    reading.write_text("1", encoding="utf-8")
    time.sleep(2)
    return records
notestore._read = stall
notestore.dismiss(root, sys.argv[3])
"""

HOLD_THE_LOCK = """
import sys, time
from pathlib import Path
from tmt import paths
root, ready, release = (Path(argument) for argument in sys.argv[1:4])
with paths.locked(root):
    ready.write_text("1", encoding="utf-8")
    deadline = time.monotonic() + 120
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
"""


def _spawn(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(SRC_DIR)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        environment.update(env)
    return subprocess.Popen(
        command,
        cwd=None if cwd is None else os.fspath(cwd),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def spawn_python(program: str, *arguments: str) -> subprocess.Popen[str]:
    """Start ``program`` in a child interpreter that can import tmt."""
    return _spawn([sys.executable, "-c", program, *arguments])


def spawn_tmt(
    cwd: Path, *arguments: str, env: dict[str, str] | None = None
) -> subprocess.Popen[str]:
    """Start ``tmt`` without waiting: concurrency needs several at once."""
    return _spawn(
        [sys.executable, "-m", "tmt", *arguments], cwd=cwd, env=env
    )


def run_tmt_after(
    root: Path, prelude: str, *arguments: str
) -> subprocess.CompletedProcess[str]:
    """Run ``tmt`` in the same process ``prelude`` ran in.

    ``os.execv`` keeps the pid and the umask, which a plain subprocess
    cannot: the caller needs both to reach tmt's own write paths.
    """
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(SRC_DIR)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    program = (
        "import os, sys\n"
        f"{prelude}\n"
        "argv = [sys.executable, '-m', 'tmt', *sys.argv[1:]]\n"
        "os.execv(sys.executable, argv)"
    )
    return subprocess.run(
        [sys.executable, "-c", program, *arguments],
        cwd=os.fspath(root),
        env=environment,
        capture_output=True,
        text=True,
    )


def _entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "purpose": "p",
        "stage": "draft",
        "usage": "tools/x [--json]",
    }
    entry.update(overrides)
    return entry


class ContainmentTest(TmtTestCase):
    def test_new_refuses_a_tools_directory_symlinked_outside(self) -> None:
        outside = self.make_dir()
        root = self.make_repo()
        (root / "tools").symlink_to(outside)
        result = run_tmt(root, "new", "helper", "--json")
        payload = self.assert_json_error(result, "containment", 3)
        self.assertIn("outside the repository", payload["error"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_init_refuses_a_dangling_tmt_json_symlink(self) -> None:
        outside = self.make_dir()
        root = self.make_dir()
        planted = outside / "planted.json"
        (root / "tmt.json").symlink_to(planted)
        result = run_tmt(root, "init", "--json")
        self.assert_json_error(result, "already-exists", 3)
        self.assertFalse(planted.exists())

    def test_agents_write_refuses_a_symlink_outside_the_repo(self) -> None:
        outside = self.make_dir()
        global_rules = outside / "CLAUDE.md"
        global_rules.write_text("GLOBAL RULES\n", encoding="utf-8")
        root = self.make_repo()
        (root / "AGENTS.md").symlink_to(global_rules)
        result = run_tmt(root, "agents", "--write", "--json")
        self.assert_json_error(result, "containment", 3)
        self.assertEqual(
            global_rules.read_text(encoding="utf-8"), "GLOBAL RULES\n"
        )

    def test_vendor_refuses_a_source_tool_symlinked_outside(self) -> None:
        secret_dir = self.make_dir()
        secret = secret_dir / "id_rsa"
        secret.write_text("PRIVATE KEY\n", encoding="utf-8")
        source = self.make_repo()
        destination = self.make_repo()
        (source / "tools").mkdir(exist_ok=True)
        (source / "tools" / "leak").symlink_to(secret)
        data = load_registry(source)
        data["tools"]["leak"] = _entry()
        save_registry(source, data)
        result = run_tmt(destination, "vendor", os.fspath(source), "leak")
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("outside the repository", result.stderr)
        self.assertFalse((destination / "tools" / "leak").exists())

    def test_vendor_refusal_copies_nothing_at_all(self) -> None:
        outside = self.make_dir()
        secret = outside / "notes.md"
        secret.write_text("PRIVATE\n", encoding="utf-8")
        source = self.make_repo()
        destination = self.make_repo()
        self.assertEqual(run_tmt(source, "new", "alpha").returncode, 0)
        # The tool itself is contained; only its long doc escapes.
        (source / "tools" / "alpha.md").symlink_to(secret)

        result = run_tmt(destination, "vendor", os.fspath(source), "alpha")

        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("outside the repository", result.stderr)
        self.assertFalse((destination / "tools" / "alpha").exists())
        self.assertFalse((destination / "tools" / "alpha.md").exists())
        self.assertEqual(self.check_json(destination)[0], 0)

    def test_check_fails_a_tool_symlinked_outside_the_repo(self) -> None:
        outside = self.make_dir()
        planted = outside / "planted"
        write_executable(planted, "#!/bin/sh\necho hi\n")
        root = self.make_repo()
        (root / "tools").mkdir(exist_ok=True)
        (root / "tools" / "escapee").symlink_to(planted)
        data = load_registry(root)
        data["tools"]["escapee"] = _entry(lang="sh")
        save_registry(root, data)
        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 1)
        self.assertTrue(
            any("outside the repository" in failure for failure in failures),
            failures,
        )

    def test_new_refuses_to_overwrite_an_existing_test_file(self) -> None:
        root = self.make_repo()
        (root / "tools").mkdir(exist_ok=True)
        handwritten = root / "tools" / "keeper.test"
        handwritten.write_text("# hand-written assertions\n", encoding="utf-8")
        result = run_tmt(root, "new", "keeper", "--json")
        self.assert_json_error(result, "already-exists", 3)
        self.assertEqual(
            handwritten.read_text(encoding="utf-8"),
            "# hand-written assertions\n",
        )
        self.assertFalse((root / "tools" / "keeper").exists())


class AgentsBlockTest(TmtTestCase):
    def test_crlf_file_keeps_its_line_endings(self) -> None:
        root = self.make_repo()
        original = (
            b"Header line\r\n\r\n<!-- tmt:agents v1 -->\r\nSTALE\r\n"
            b"<!-- /tmt:agents -->\r\n\r\nTrailing prose\r\n"
        )
        (root / "AGENTS.md").write_bytes(original)
        result = run_tmt(root, "agents", "--write", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        written = (root / "AGENTS.md").read_bytes()
        self.assertEqual(written.count(b"\n"), written.count(b"\r\n"))
        self.assertTrue(written.startswith(b"Header line\r\n\r\n"))
        self.assertTrue(written.endswith(b"\r\n\r\nTrailing prose\r\n"))
        self.assertEqual(self.check_json(root)[0], 0)

    def test_a_marker_example_does_not_claim_the_content_below(self) -> None:
        root = self.make_repo()
        original = (
            "The block looks like this:\n\n"
            "<!-- tmt:agents-example -->\n"
            "MY OWN RULES\n"
            "<!-- /tmt:agents -->\n"
        )
        (root / "AGENTS.md").write_text(original, encoding="utf-8")
        result = run_tmt(root, "agents", "--write", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("MY OWN RULES", text)
        self.assertIn("<!-- tmt:agents-example -->", text)

    def test_duplicate_blocks_fail_the_check_and_refuse_a_write(self) -> None:
        root = self.make_repo()
        self.assertEqual(
            run_tmt(root, "agents", "--write").returncode, 0
        )
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "\n<!-- tmt:agents v1 -->\nOLD\n<!-- /tmt:agents -->\n"
            )
        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 1)
        self.assertTrue(
            any("more than one tmt block" in failure for failure in failures),
            failures,
        )
        self.assert_json_error(
            run_tmt(root, "agents", "--write", "--json"), "check-failed", 3
        )


class AtomicWriteTest(TmtTestCase):
    def test_registry_save_leaves_no_staging_file_behind(self) -> None:
        root = self.make_repo()
        result = run_tmt(root, "new", "alpha", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        strays = [
            item.name
            for item in root.iterdir()
            if item.name.endswith(".tmt-tmp")
        ]
        self.assertEqual(strays, [])
        self.assertIn("alpha", load_registry(root)["tools"])

    def test_a_leftover_staging_file_does_not_block_the_save(self) -> None:
        root = self.make_repo()

        result = run_tmt_after(
            root, PLANT_STALE_STAGE, "new", "alpha", "--json"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("alpha", load_registry(root)["tools"])
        strays = [
            item.name
            for item in root.iterdir()
            if item.name.endswith(".tmt-tmp")
        ]
        self.assertEqual(len(strays), 1, strays)

    def test_registry_save_preserves_an_in_repo_symlink(self) -> None:
        root = self.make_repo()
        real = root / "registry-real.json"
        (root / "tmt.json").rename(real)
        (root / "tmt.json").symlink_to(real.name)
        result = run_tmt(root, "new", "alpha", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((root / "tmt.json").is_symlink())
        self.assertIn(
            "alpha", json.loads(real.read_text(encoding="utf-8"))["tools"]
        )


class MutationLockTest(TmtTestCase):
    """One process must not silently drop another's work.

    `tmt new` is where the lost update was found: two of them each loaded
    tmt.json, added an entry, and the second save dropped the first one's
    tool, leaving scaffolded files with no entry and `tmt check` red. The
    note store lost notes the same way.
    """

    def setUp(self) -> None:
        # `tmt note` mirrors to aiq when it is on PATH; an empty PATH keeps
        # these tests off any real journal.
        self.sandbox = {
            "HOME": os.fspath(self.make_dir()),
            "PATH": os.fspath(self.make_dir()),
        }

    def reap(self, child: subprocess.Popen[str]) -> None:
        """Close the pipes and wait, unless the body already did."""
        if child.returncode is None:
            child.communicate(timeout=120)

    def hold_the_lock(self, root: Path) -> tuple[subprocess.Popen[str], Path]:
        """Start a child holding ``root``'s lock; release it on cleanup."""
        signals = self.make_dir()
        ready = signals / "ready"
        release = signals / "release"
        holder = spawn_python(
            HOLD_THE_LOCK,
            os.fspath(root),
            os.fspath(ready),
            os.fspath(release),
        )

        def finish() -> None:
            release.touch()
            self.reap(holder)

        self.addCleanup(finish)
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline:
            self.assertIsNone(holder.poll(), "the lock holder died early")
            time.sleep(0.02)
        self.assertTrue(ready.exists(), "the lock holder never acquired")
        return holder, release

    def test_concurrent_new_keeps_every_entry(self) -> None:
        root = self.make_repo()
        ids = [f"t{index}" for index in range(CONCURRENT_WORKERS)]
        workers: list[tuple[str, subprocess.Popen[str]]] = []
        for tool_id in ids:
            worker = spawn_tmt(root, "new", tool_id, env=self.sandbox)
            self.addCleanup(self.reap, worker)
            workers.append((tool_id, worker))
        for tool_id, worker in workers:
            _, errors = worker.communicate(timeout=120)
            self.assertEqual(worker.returncode, 0, f"{tool_id}: {errors}")

        self.assertEqual(sorted(load_registry(root)["tools"]), ids)
        scaffolded = sorted(
            path.name
            for path in (root / "tools").iterdir()
            if not path.name.endswith(".test")
        )
        self.assertEqual(scaffolded, ids)
        self.assertEqual(self.check_json(root), (0, [], []))

    def test_a_held_lock_fails_a_mutation_instead_of_hanging(self) -> None:
        root = self.make_repo()
        self.hold_the_lock(root)

        started = time.monotonic()
        result = run_tmt(
            root, "note", "reused-derivation", "--json", env=self.sandbox
        )
        waited = time.monotonic() - started

        payload = self.assert_json_error(result, "io-error", 3)
        self.assertIn("lock", payload["error"])
        self.assertIn("gave up waiting", payload["error"])
        self.assertLess(waited, 60, "the bounded wait was not bounded")

    def test_a_waiting_mutation_lands_once_the_lock_is_free(self) -> None:
        root = self.make_repo()
        holder, release = self.hold_the_lock(root)

        release.touch()
        self.reap(holder)
        result = run_tmt(
            root, "note", "reused-derivation", "--json", env=self.sandbox
        )

        self.assertEqual(self.assert_json_success(result)["count"], 1)

    def test_a_note_taken_during_a_dismiss_is_not_erased(self) -> None:
        root = self.make_repo()
        for _ in range(2):
            self.assertEqual(
                run_tmt(root, "note", "gone", env=self.sandbox).returncode, 0
            )
        reading = self.make_dir() / "reading"
        dismisser = spawn_python(
            SLOW_DISMISS, os.fspath(root), os.fspath(reading), "gone"
        )
        self.addCleanup(self.reap, dismisser)
        deadline = time.monotonic() + 60
        while not reading.exists() and time.monotonic() < deadline:
            self.assertIsNone(dismisser.poll(), "the dismiss died early")
            time.sleep(0.02)
        self.assertTrue(reading.exists(), "the dismiss never read the store")

        noted = run_tmt(root, "note", "keeper", env=self.sandbox)

        self.assertEqual(noted.returncode, 0, noted.stderr)
        _, errors = dismisser.communicate(timeout=120)
        self.assertEqual(dismisser.returncode, 0, errors)
        remaining = self.assert_json_success(
            run_tmt(root, "candidates", "--json", env=self.sandbox)
        )["candidates"]
        self.assertEqual([row["slug"] for row in remaining], ["keeper"])

    def test_the_lock_never_becomes_a_work_tree_file(self) -> None:
        root = self.make_repo()
        git_init_commit(root)

        result = run_tmt(root, "note", "reused-derivation", env=self.sandbox)
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertEqual(run_git(root, "status", "--porcelain"), "")
        self.assertTrue((root / ".git" / "tmt" / "lock").is_file())


class FileModeTest(TmtTestCase):
    def test_a_new_tool_stays_executable_under_a_tight_umask(self) -> None:
        root = self.make_repo()

        result = run_tmt_after(
            root, RESTRICTIVE_UMASK, "new", "alpha", "--json"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("alpha", "alpha.test"):
            mode = (root / "tools" / name).stat().st_mode & 0o777
            self.assertEqual(oct(mode), oct(0o755), name)

    def test_a_new_registry_stays_readable_under_a_tight_umask(self) -> None:
        root = self.make_dir()

        result = run_tmt_after(root, RESTRICTIVE_UMASK, "init", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        mode = (root / "tmt.json").stat().st_mode & 0o777
        self.assertEqual(oct(mode), oct(0o644))


class RegistryValidationTest(TmtTestCase):
    def test_id_with_a_trailing_newline_is_invalid(self) -> None:
        root = self.make_repo()
        save_registry(
            root, {"tools": {"fmt-json\n": _entry()}, "v": 1}
        )
        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 1)
        self.assertTrue(
            any("tool id must match" in failure for failure in failures),
            failures,
        )

    def test_overlong_id_is_reported_with_the_cap(self) -> None:
        root = self.make_repo()
        save_registry(root, {"tools": {"a" * 65: _entry()}, "v": 1})
        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 1)
        self.assertTrue(
            any("the cap is 64" in failure for failure in failures), failures
        )

    def test_new_refuses_an_overlong_id_as_usage(self) -> None:
        root = self.make_repo()
        result = run_tmt(root, "new", "a" * 65, "--json")
        self.assert_json_error(result, "usage", 2)

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_unreadable_registry_is_an_io_error_not_a_defect(self) -> None:
        root = self.make_repo()
        registry_path = root / "tmt.json"
        registry_path.chmod(0o000)
        self.addCleanup(registry_path.chmod, 0o644)
        result = run_tmt(root, "list", "--json")
        self.assert_json_error(result, "io-error", 3)

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_check_reports_an_unreadable_registry_as_a_failure(self) -> None:
        root = self.make_repo()
        registry_path = root / "tmt.json"
        registry_path.chmod(0o000)
        self.addCleanup(registry_path.chmod, 0o644)
        result = run_tmt(root, "check", "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = self.parse_single_json(result.stdout)
        self.assertTrue(
            any(
                "cannot be read" in failure
                for failure in payload["failures"]
            ),
            payload["failures"],
        )

    def test_non_utf8_registry_is_a_check_failure(self) -> None:
        root = self.make_repo()
        (root / "tmt.json").write_bytes(b'{"v": 1, "tools": {}}\xff')
        result = run_tmt(root, "list", "--json")
        self.assert_json_error(result, "check-failed", 3)

    def test_deep_requires_chain_does_not_exhaust_the_stack(self) -> None:
        root = self.make_repo()
        depth = 3000
        tools = {
            f"t{index}": _entry(
                requires=[f"t{index + 1}"] if index < depth - 1 else []
            )
            for index in range(depth)
        }
        save_registry(root, {"tools": tools, "v": 1})
        result = run_tmt(root, "check", "--json")
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertEqual(result.stderr, "")


class ToolOutputSafetyTest(TmtTestCase):
    def test_show_escapes_control_characters_from_tool_help(self) -> None:
        root = self.make_repo()
        result = run_tmt(root, "new", "noisy", "--lang", "sh", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        write_executable(
            root / "tools" / "noisy",
            "#!/bin/sh\nprintf 'safe\\033]0;pwned\\007text\\n'\n",
        )
        shown = run_tmt(root, "show", "noisy")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn("\033", shown.stdout)
        self.assertIn("\\u001b", shown.stdout)


class ContextSafetyTest(TmtTestCase):
    def test_context_does_not_block_on_an_open_stdin(self) -> None:
        root = self.make_repo()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.fspath(
            Path(__file__).resolve().parent.parent / "src"
        )
        # An open stdin nobody writes to: an unbounded read would hang.
        with open("/dev/zero", "rb") as never_ends:
            completed = subprocess.run(
                [sys.executable, "-m", "tmt", "context"],
                cwd=os.fspath(root),
                env=environment,
                stdin=never_ends,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_context_caps_a_hostile_purpose_line(self) -> None:
        root = self.make_repo()
        save_registry(
            root,
            {
                "tools": {
                    "alpha": _entry(purpose="x" * 80),
                },
                "v": 1,
            },
        )
        result = run_tmt(root, "context")
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            self.assertLessEqual(len(line), 130, line)


if __name__ == "__main__":
    unittest.main()

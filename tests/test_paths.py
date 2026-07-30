"""Containment: tmt never writes or copies outside the repository.

A symlink is not a licence to leave. Every write path (init, new, agents
--write, vendor) resolves its target first and refuses one that lands
outside the repository root, and the registry save is atomic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _support import (
    TmtTestCase,
    load_registry,
    run_tmt,
    save_registry,
    write_executable,
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

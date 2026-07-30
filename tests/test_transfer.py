"""Vendor (copy in) and adopt (copy out) with origin provenance stamps."""

from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from _support import (
    TmtTestCase,
    git_init_commit,
    load_registry,
    run_git,
    run_tmt,
    save_registry,
    write_executable,
)

PASSING_TEST = "#!/bin/sh\nset -eu\n\"tools/{tool_id}\" --help >/dev/null\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VendorTest(TmtTestCase):
    def _source_with_stable_tool(self, tool_id: str) -> tuple[Path, str]:
        source = self.make_repo()
        run_tmt(source, "new", tool_id, "--lang", "sh", "--purpose", "Vendee")
        write_executable(
            source / "tools" / f"{tool_id}.test",
            PASSING_TEST.format(tool_id=tool_id),
        )
        (source / "tools" / f"{tool_id}.md").write_text(
            "Vendored doc.\n", encoding="utf-8"
        )
        data = load_registry(source)
        data["tools"][tool_id]["stage"] = "stable"
        save_registry(source, data)
        commit = git_init_commit(source)
        return source, commit

    def test_vendor_stamps_origin_and_copies_companions(self) -> None:
        source, commit = self._source_with_stable_tool("greet")
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")
        )

        self.assertEqual(payload["status"], "vendored")
        self.assertEqual(payload["id"], "greet")
        self.assertEqual(payload["path"], "tools/greet")
        origin = payload["origin"]
        # No origin remote in the source, so no url field is stamped.
        self.assertEqual(
            sorted(origin), ["commit", "id", "repo", "sha256"]
        )
        self.assertEqual(origin["repo"], os.fspath(source))
        self.assertEqual(origin["commit"], commit)
        self.assertRegex(origin["commit"], r"^[0-9a-f]{40}$")
        tool = dest / "tools" / "greet"
        self.assertEqual(origin["sha256"], sha256_file(tool))
        self.assertEqual(
            sha256_file(tool), sha256_file(source / "tools" / "greet")
        )
        self.assertTrue(os.access(tool, os.X_OK))
        self.assertTrue((dest / "tools" / "greet.test").is_file())
        self.assertTrue((dest / "tools" / "greet.md").is_file())
        entry = load_registry(dest)["tools"]["greet"]
        self.assertEqual(entry["stage"], "stable")
        self.assertEqual(entry["purpose"], "Vendee")
        self.assertEqual(entry["origin"], origin)

    def test_vendored_copy_passes_check_then_warns_on_source_drift(
        self,
    ) -> None:
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()
        run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")

        returncode, failures, warnings = self.check_json(dest)
        self.assertEqual((returncode, failures, warnings), (0, [], []))

        source_tool = source / "tools" / "greet"
        source_tool.write_text(
            source_tool.read_text(encoding="utf-8") + "# upstream change\n",
            encoding="utf-8",
        )

        returncode, failures, warnings = self.check_json(dest)
        self.assertEqual(returncode, 0)  # drift warns, never fails
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("greet", warnings[0])
        self.assertIn("has a newer version", warnings[0])
        human = run_tmt(dest, "check")
        self.assertEqual(human.returncode, 0)
        self.assertTrue(
            any(
                line.startswith("WARN ")
                for line in human.stdout.splitlines()
            ),
            human.stdout,
        )

    def test_local_fork_alone_is_silent(self) -> None:
        """Divergence after vendoring is sanctioned, so it must not warn.

        Comparing only source-now against local-now cannot tell a local
        fork from an upstream change, and warned with advice that would
        discard the fork.
        """
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()
        run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")

        local = dest / "tools" / "greet"
        local.write_text(
            local.read_text(encoding="utf-8") + "# local tweak\n",
            encoding="utf-8",
        )

        returncode, failures, warnings = self.check_json(dest)
        self.assertEqual((returncode, failures, warnings), (0, [], []))

    def test_both_sides_changed_warns_about_losing_local_work(self) -> None:
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()
        run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")

        local = dest / "tools" / "greet"
        local.write_text(
            local.read_text(encoding="utf-8") + "# local tweak\n",
            encoding="utf-8",
        )
        source_tool = source / "tools" / "greet"
        source_tool.write_text(
            source_tool.read_text(encoding="utf-8") + "# upstream change\n",
            encoding="utf-8",
        )

        returncode, failures, warnings = self.check_json(dest)
        self.assertEqual(returncode, 0)
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("both this copy and", warnings[0])
        self.assertIn("discard the local changes", warnings[0])

    def test_origin_records_the_source_side_id(self) -> None:
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()
        payload = self.assert_json_success(
            run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")
        )
        self.assertEqual(payload["origin"]["id"], "greet")

    def test_renaming_a_vendored_tool_keeps_its_drift_reporting(self) -> None:
        """Drift derives the source path from the id it was vendored under.

        Deriving it from the current id meant a local rename pointed at a
        path that never existed upstream, and drift went silent.
        """
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()
        run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")
        source_tool = source / "tools" / "greet"
        source_tool.write_text(
            source_tool.read_text(encoding="utf-8") + "# upstream\n",
            encoding="utf-8",
        )
        self.assertEqual(
            len(self.check_json(dest)[2]), 1, "expected drift before rename"
        )

        renamed = run_tmt(dest, "rename", "greet", "hello", "--json")
        self.assertEqual(renamed.returncode, 0, renamed.stderr)
        test = dest / "tools" / "hello.test"
        test.write_text(
            PASSING_TEST.format(tool_id="hello"), encoding="utf-8"
        )
        test.chmod(0o755)

        returncode, failures, warnings = self.check_json(dest)
        self.assertEqual((returncode, failures), (0, []))
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("hello", warnings[0])
        self.assertIn("has a newer version", warnings[0])

    def test_vendor_stamps_url_when_source_has_origin_remote(self) -> None:
        source, _ = self._source_with_stable_tool("greet")
        run_git(
            source,
            "remote",
            "add",
            "origin",
            "https://example.invalid/tmt-lib.git",
        )
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(dest, "vendor", os.fspath(source), "greet", "--json")
        )

        origin = payload["origin"]
        self.assertEqual(
            sorted(origin), ["commit", "id", "repo", "sha256", "url"]
        )
        self.assertEqual(
            origin["url"], "https://example.invalid/tmt-lib.git"
        )
        self.assertEqual(
            load_registry(dest)["tools"]["greet"]["origin"], origin
        )
        # The optional url field validates: the vendored repo still checks.
        returncode, failures, warnings = self.check_json(dest)
        self.assertEqual((returncode, failures, warnings), (0, [], []))

    def test_vendor_human_prints_path(self) -> None:
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()

        result = run_tmt(dest, "vendor", os.fspath(source), "greet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "tools/greet\n")

    def test_vendor_refuses_a_symlinked_destination(self) -> None:
        source, _ = self._source_with_stable_tool("payload")
        dest = self.make_repo()
        outside = self.make_dir() / "OUTSIDE.txt"
        (dest / "tools").mkdir(exist_ok=True)
        (dest / "tools" / "payload").symlink_to(outside)

        payload = self.assert_json_error(
            run_tmt(dest, "vendor", os.fspath(source), "payload", "--json"),
            "containment",
            3,
        )

        self.assertIn("destination tools/payload", payload["error"])
        self.assertFalse(outside.exists())
        self.assertEqual(load_registry(dest)["tools"], {})

    def test_vendor_refuses_a_symlinked_destination_companion(self) -> None:
        source, _ = self._source_with_stable_tool("payload")
        dest = self.make_repo()
        outside = self.make_dir() / "OUTSIDE.md"
        (dest / "tools").mkdir(exist_ok=True)
        (dest / "tools" / "payload.md").symlink_to(outside)

        payload = self.assert_json_error(
            run_tmt(dest, "vendor", os.fspath(source), "payload", "--json"),
            "containment",
            3,
        )

        self.assertIn("destination tools/payload.md", payload["error"])
        self.assertFalse(outside.exists())
        # Planned before the first byte: not even the executable landed.
        self.assertFalse((dest / "tools" / "payload").exists())
        self.assertEqual(load_registry(dest)["tools"], {})

    def test_revendoring_over_a_regular_file_overwrites(self) -> None:
        source, _ = self._source_with_stable_tool("payload")
        dest = self.make_repo()
        run_tmt(dest, "vendor", os.fspath(source), "payload")
        tool = dest / "tools" / "payload"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o644)

        self.assert_json_success(
            run_tmt(dest, "vendor", os.fspath(source), "payload", "--json")
        )

        self.assertFalse(tool.is_symlink())
        self.assertEqual(
            sha256_file(tool), sha256_file(source / "tools" / "payload")
        )
        self.assertTrue(os.access(tool, os.X_OK))

    def test_vendor_from_repo_without_registry(self) -> None:
        dest = self.make_repo()
        bare = self.make_dir()

        self.assert_json_error(
            run_tmt(dest, "vendor", os.fspath(bare), "greet", "--json"),
            "no-registry",
            3,
        )

    def test_vendor_unknown_tool(self) -> None:
        source = self.make_repo()
        dest = self.make_repo()

        self.assert_json_error(
            run_tmt(dest, "vendor", os.fspath(source), "nope", "--json"),
            "not-found",
            3,
        )


class ConfigCarryTest(TmtTestCase):
    """Vendor and adopt carry `config`, remind, and never copy the files."""

    def _stable_with_config(self, tool_id: str) -> Path:
        repo = self.make_repo()
        run_tmt(repo, "new", tool_id, "--lang", "sh", "--purpose", "Budgets")
        write_executable(
            repo / "tools" / f"{tool_id}.test",
            PASSING_TEST.format(tool_id=tool_id),
        )
        data = load_registry(repo)
        data["tools"][tool_id]["config"] = [".doc-budgets.json"]
        data["tools"][tool_id]["stage"] = "stable"
        save_registry(repo, data)
        (repo / ".doc-budgets.json").write_text("{}\n", encoding="utf-8")
        return repo

    def test_vendor_carries_config_and_reminds(self) -> None:
        source = self._stable_with_config("budgets")
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(dest, "vendor", os.fspath(source), "budgets", "--json")
        )

        self.assertEqual(payload["config"], [".doc-budgets.json"])
        entry = load_registry(dest)["tools"]["budgets"]
        self.assertEqual(entry["config"], [".doc-budgets.json"])
        # The config file itself is never copied: config is repo-specific.
        self.assertFalse((dest / ".doc-budgets.json").exists())

        human_dest = self.make_repo()
        result = run_tmt(
            human_dest, "vendor", os.fspath(source), "budgets"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "tools/budgets\n"
            "note: reads .doc-budgets.json; create them in this repo\n",
        )

    def test_vendor_without_config_stays_quiet(self) -> None:
        source = self._stable_with_config("budgets")
        data = load_registry(source)
        del data["tools"]["budgets"]["config"]
        save_registry(source, data)
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(dest, "vendor", os.fspath(source), "budgets", "--json")
        )
        self.assertNotIn("config", payload)

        human_dest = self.make_repo()
        result = run_tmt(
            human_dest, "vendor", os.fspath(source), "budgets"
        )
        self.assertEqual(result.stdout, "tools/budgets\n")

    def test_adopt_carries_config_and_reminds(self) -> None:
        repo = self._stable_with_config("budgets")
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(
                repo, "adopt", "budgets", "--to", os.fspath(dest), "--json"
            )
        )

        self.assertEqual(payload["config"], [".doc-budgets.json"])
        entry = load_registry(dest)["tools"]["budgets"]
        self.assertEqual(entry["config"], [".doc-budgets.json"])
        self.assertFalse((dest / ".doc-budgets.json").exists())

        human_dest = self.make_repo()
        result = run_tmt(
            repo, "adopt", "budgets", "--to", os.fspath(human_dest)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"budgets -> {os.fspath(human_dest)}\n"
            "note: reads .doc-budgets.json; create them in the "
            "destination repo\n",
        )


class AdoptTest(TmtTestCase):
    def _new_stable(self, repo, tool_id: str, *extra: str) -> None:
        """Scaffold, write a real (non-scaffold) test, and promote."""
        run_tmt(repo, "new", tool_id, "--lang", "sh", *extra)
        write_executable(
            repo / "tools" / f"{tool_id}.test",
            PASSING_TEST.format(tool_id=tool_id),
        )
        result = run_tmt(repo, "stage", tool_id, "stable")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_adopt_copies_out_with_origin_stamp(self) -> None:
        repo = self.make_repo()
        self._new_stable(repo, "clean", "--purpose", "Portable")
        commit = git_init_commit(repo)
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(repo, "adopt", "clean", "--to", os.fspath(dest), "--json")
        )

        self.assertEqual(payload["status"], "adopted")
        self.assertEqual(payload["id"], "clean")
        self.assertEqual(payload["to"], os.fspath(dest))
        origin = payload["origin"]
        self.assertNotIn("url", origin)  # no origin remote configured
        self.assertEqual(origin["repo"], os.fspath(repo))
        self.assertEqual(origin["commit"], commit)
        tool = dest / "tools" / "clean"
        self.assertTrue(os.access(tool, os.X_OK))
        self.assertEqual(origin["sha256"], sha256_file(tool))
        entry = load_registry(dest)["tools"]["clean"]
        self.assertEqual(entry["purpose"], "Portable")
        self.assertEqual(entry["origin"], origin)

    def test_adopt_stamps_url_when_repo_has_origin_remote(self) -> None:
        repo = self.make_repo()
        self._new_stable(repo, "clean")
        git_init_commit(repo)
        run_git(
            repo, "remote", "add", "origin", "ssh://example.invalid/work.git"
        )
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(repo, "adopt", "clean", "--to", os.fspath(dest), "--json")
        )

        origin = payload["origin"]
        self.assertEqual(origin["url"], "ssh://example.invalid/work.git")
        self.assertEqual(
            load_registry(dest)["tools"]["clean"]["origin"], origin
        )

    def test_adopt_refuses_draft_tool(self) -> None:
        repo = self.make_repo()
        run_tmt(repo, "new", "young", "--lang", "sh")
        dest = self.make_repo()

        payload = self.assert_json_error(
            run_tmt(
                repo, "adopt", "young", "--to", os.fspath(dest), "--json"
            ),
            "portability",
            3,
        )

        self.assertIn("only stable tools can be adopted", payload["error"])
        self.assertEqual(load_registry(dest)["tools"], {})
        self.assertFalse((dest / "tools" / "young").exists())

    def test_adopt_rejects_home_path_with_portability_error(self) -> None:
        repo = self.make_repo()
        run_tmt(repo, "new", "sticky", "--lang", "sh")
        tool = repo / "tools" / "sticky"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + "cat /home/example/notes >/dev/null\n",
            encoding="utf-8",
        )
        # Flip the stage by hand: `tmt stage` would already refuse this
        # body, and adopt must lint it independently.
        data = load_registry(repo)
        data["tools"]["sticky"]["stage"] = "stable"
        save_registry(repo, data)
        dest = self.make_repo()

        payload = self.assert_json_error(
            run_tmt(
                repo, "adopt", "sticky", "--to", os.fspath(dest), "--json"
            ),
            "portability",
            3,
        )

        self.assertIn("/home/", payload["error"])
        self.assertEqual(load_registry(dest)["tools"], {})
        self.assertFalse((dest / "tools" / "sticky").exists())

    def test_adopt_rejects_unpromoted_dependency(self) -> None:
        repo = self.make_repo()
        self._new_stable(repo, "helper")
        run_tmt(repo, "new", "top", "--lang", "sh")
        write_executable(
            repo / "tools" / "top.test", PASSING_TEST.format(tool_id="top")
        )
        data = load_registry(repo)
        data["tools"]["top"]["requires"] = ["helper"]
        save_registry(repo, data)
        result = run_tmt(repo, "stage", "top", "stable")
        self.assertEqual(result.returncode, 0, result.stderr)
        dest = self.make_repo()

        payload = self.assert_json_error(
            run_tmt(repo, "adopt", "top", "--to", os.fspath(dest), "--json"),
            "portability",
            3,
        )

        self.assertIn("helper", payload["error"])

    def test_adopt_refuses_a_symlinked_destination(self) -> None:
        repo = self.make_repo()
        self._new_stable(repo, "clean")
        dest = self.make_repo()
        outside = self.make_dir() / "OUTSIDE.txt"
        (dest / "tools").mkdir(exist_ok=True)
        (dest / "tools" / "clean").symlink_to(outside)

        payload = self.assert_json_error(
            run_tmt(repo, "adopt", "clean", "--to", os.fspath(dest), "--json"),
            "containment",
            3,
        )

        self.assertIn("destination tools/clean", payload["error"])
        self.assertFalse(outside.exists())
        self.assertEqual(load_registry(dest)["tools"], {})

    def test_adopt_to_destination_without_registry(self) -> None:
        repo = self.make_repo()
        self._new_stable(repo, "clean")
        bare = self.make_dir()

        self.assert_json_error(
            run_tmt(repo, "adopt", "clean", "--to", os.fspath(bare), "--json"),
            "no-registry",
            3,
        )

    def test_adopt_unknown_tool(self) -> None:
        repo = self.make_repo()
        dest = self.make_repo()

        self.assert_json_error(
            run_tmt(repo, "adopt", "nope", "--to", os.fspath(dest), "--json"),
            "not-found",
            3,
        )


if __name__ == "__main__":
    unittest.main()

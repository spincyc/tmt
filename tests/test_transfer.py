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
        self.assertEqual(
            sorted(origin), ["commit", "repo", "sha256"]
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
        self.assertIn("sha256 drift", warnings[0])
        human = run_tmt(dest, "check")
        self.assertEqual(human.returncode, 0)
        self.assertTrue(
            any(
                line.startswith("WARN ")
                for line in human.stdout.splitlines()
            ),
            human.stdout,
        )

    def test_vendor_human_prints_path(self) -> None:
        source, _ = self._source_with_stable_tool("greet")
        dest = self.make_repo()

        result = run_tmt(dest, "vendor", os.fspath(source), "greet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "tools/greet\n")

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


class AdoptTest(TmtTestCase):
    def test_adopt_copies_out_with_origin_stamp(self) -> None:
        repo = self.make_repo()
        run_tmt(repo, "new", "clean", "--lang", "sh", "--purpose", "Portable")
        commit = git_init_commit(repo)
        dest = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(repo, "adopt", "clean", "--to", os.fspath(dest), "--json")
        )

        self.assertEqual(payload["status"], "adopted")
        self.assertEqual(payload["id"], "clean")
        self.assertEqual(payload["to"], os.fspath(dest))
        origin = payload["origin"]
        self.assertEqual(origin["repo"], os.fspath(repo))
        self.assertEqual(origin["commit"], commit)
        tool = dest / "tools" / "clean"
        self.assertTrue(os.access(tool, os.X_OK))
        self.assertEqual(origin["sha256"], sha256_file(tool))
        entry = load_registry(dest)["tools"]["clean"]
        self.assertEqual(entry["purpose"], "Portable")
        self.assertEqual(entry["origin"], origin)

    def test_adopt_rejects_home_path_with_portability_error(self) -> None:
        repo = self.make_repo()
        run_tmt(repo, "new", "sticky", "--lang", "sh")
        tool = repo / "tools" / "sticky"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + "cat /home/example/notes >/dev/null\n",
            encoding="utf-8",
        )
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
        run_tmt(repo, "new", "top", "--lang", "sh")
        run_tmt(repo, "new", "helper", "--lang", "sh")
        data = load_registry(repo)
        data["tools"]["top"]["requires"] = ["helper"]
        save_registry(repo, data)
        dest = self.make_repo()

        payload = self.assert_json_error(
            run_tmt(repo, "adopt", "top", "--to", os.fspath(dest), "--json"),
            "portability",
            3,
        )

        self.assertIn("helper", payload["error"])

    def test_adopt_to_destination_without_registry(self) -> None:
        repo = self.make_repo()
        run_tmt(repo, "new", "clean", "--lang", "sh")
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

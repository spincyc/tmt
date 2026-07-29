"""The tmt check gate battery: born-passing scaffolds and each failure."""

from __future__ import annotations

import os
import unittest

from _support import (
    TmtTestCase,
    load_registry,
    run_tmt,
    save_registry,
    write_executable,
)

PASSING_TEST = "#!/bin/sh\nset -eu\n\"tools/{tool_id}\" --help >/dev/null\n"


class ScaffoldCheckTest(TmtTestCase):
    def test_fresh_scaffolds_pass_check_for_both_langs(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "pytool")
        run_tmt(root, "new", "shtool", "--lang", "sh")

        returncode, failures, warnings = self.check_json(root)

        self.assertEqual(failures, [])
        self.assertEqual(warnings, [])
        self.assertEqual(returncode, 0)
        human = run_tmt(root, "check")
        self.assertEqual(human.returncode, 0)
        self.assertEqual(human.stdout, "ok\n")

    def test_empty_registry_passes(self) -> None:
        root = self.make_repo()

        returncode, failures, warnings = self.check_json(root)

        self.assertEqual((returncode, failures, warnings), (0, [], []))

    def test_check_without_registry_reports_no_registry(self) -> None:
        root = self.make_dir()

        self.assert_json_error(
            run_tmt(root, "check", "--json"), "no-registry", 3
        )


class DraftGateTest(TmtTestCase):
    def test_missing_file_for_entry(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "ghost")
        (root / "tools" / "ghost").unlink()

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures, ["ghost: tools/ghost missing for tmt.json entry"]
        )

    def test_orphan_file_without_entry(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "real")
        (root / "tools" / "stray").write_text("#!/bin/sh\n", encoding="utf-8")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(failures, ["tools/stray: file has no tmt.json entry"])

    def test_companion_files_are_not_orphans(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "real")
        (root / "tools" / "real.md").write_text("doc\n", encoding="utf-8")
        write_executable(root / "tools" / "real.test", "#!/bin/sh\nexit 0\n")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))

    def test_purpose_over_80_characters(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "wordy")
        data = load_registry(root)
        data["tools"]["wordy"]["purpose"] = "x" * 81
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("purpose", failures[0])
        self.assertIn("81", failures[0])
        self.assertIn("80", failures[0])

    def test_unresolved_requires(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "alpha")
        data = load_registry(root)
        data["tools"]["alpha"]["requires"] = ["ghost"]
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures, ["alpha: requires 'ghost' which is not registered"]
        )

    def test_dependency_cycle(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "alpha")
        run_tmt(root, "new", "beta")
        data = load_registry(root)
        data["tools"]["alpha"]["requires"] = ["beta"]
        data["tools"]["beta"]["requires"] = ["alpha"]
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertTrue(
            any(failure.startswith("requires cycle:") for failure in failures),
            failures,
        )

    def test_python_syntax_error(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "broken")
        tool = root / "tools" / "broken"
        write_executable(tool, "#!/usr/bin/env python3\ndef (\n")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertTrue(
            any("python syntax error" in failure for failure in failures),
            failures,
        )

    def test_sh_syntax_error(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "broken", "--lang", "sh")
        write_executable(root / "tools" / "broken", "#!/bin/sh\nif then fi\n")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertTrue(
            any("sh syntax error" in failure for failure in failures),
            failures,
        )

    def test_executable_bit_not_set(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "flat")
        (root / "tools" / "flat").chmod(0o644)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures, ["flat: executable bit not set on tools/flat"]
        )

    def test_help_failure(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "grumpy", "--lang", "sh")
        write_executable(root / "tools" / "grumpy", "#!/bin/sh\nexit 7\n")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(failures, ["grumpy: --help exited 7"])


class StableGateTest(TmtTestCase):
    def _make_stable(self, root, tool_id: str, *, with_test: bool = True):
        run_tmt(root, "new", tool_id, "--lang", "sh")
        if with_test:
            write_executable(
                root / "tools" / f"{tool_id}.test",
                PASSING_TEST.format(tool_id=tool_id),
            )
        data = load_registry(root)
        data["tools"][tool_id]["stage"] = "stable"
        save_registry(root, data)

    def test_stable_scaffold_with_test_passes(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "solid")

        returncode, failures, warnings = self.check_json(root)

        self.assertEqual((returncode, failures, warnings), (0, [], []))

    def test_stable_without_test_file(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "untested", with_test=False)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            ["untested: stable tool is missing tools/untested.test"],
        )

    def test_stable_failing_test(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "flaky")
        write_executable(root / "tools" / "flaky.test", "#!/bin/sh\nexit 1\n")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(failures, ["flaky: tools/flaky.test exited 1"])

    def test_stable_requires_draft(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "top")
        run_tmt(root, "new", "helper", "--lang", "sh")
        data = load_registry(root)
        data["tools"]["top"]["requires"] = ["helper"]
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures, ["top: stable tool requires draft 'helper'"]
        )

    def test_hardcoded_home_path_in_stable_tool(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "rooted")
        tool = root / "tools" / "rooted"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + "# data lives in /home/example/data\n",
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            [
                "rooted: hardcoded absolute path: body contains '/home/'"
            ],
        )

    def test_hardcoded_repo_path_in_stable_tool(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "selfish")
        tool = root / "tools" / "selfish"
        tool.write_text(
            tool.read_text(encoding="utf-8") + f"# see {os.fspath(root)}\n",
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("hardcoded absolute path", failures[0])
        self.assertIn("repo", failures[0])

    def test_draft_tools_skip_stable_gates(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "loose", "--lang", "sh")
        tool = root / "tools" / "loose"
        tool.write_text(
            tool.read_text(encoding="utf-8") + "# /home/example/ok-in-draft\n",
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))


class HumanOutputTest(TmtTestCase):
    def test_failures_are_fail_prefixed_lines(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "one")
        run_tmt(root, "new", "two")
        (root / "tools" / "one").unlink()
        (root / "tools" / "two").unlink()

        result = run_tmt(root, "check")

        self.assertEqual(result.returncode, 1)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertTrue(line.startswith("FAIL "), line)


if __name__ == "__main__":
    unittest.main()

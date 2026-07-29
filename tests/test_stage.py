"""tmt stage: gated promotion and demotion through the registry serializer."""

from __future__ import annotations

import unittest

from _support import (
    TmtTestCase,
    load_registry,
    run_tmt,
    save_registry,
    write_executable,
)

PASSING_TEST = "#!/bin/sh\nset -eu\n\"tools/{tool_id}\" --help >/dev/null\n"


class StagePromoteTest(TmtTestCase):
    def test_promotion_refused_when_test_is_missing(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "raw", "--lang", "sh")
        (root / "tools" / "raw.test").unlink()

        payload = self.assert_json_error(
            run_tmt(root, "stage", "raw", "stable", "--json"),
            "check-failed",
            3,
        )

        self.assertIn("raw.test", payload["error"])
        self.assertEqual(load_registry(root)["tools"]["raw"]["stage"], "draft")

    def test_promotion_succeeds_after_adding_a_test(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "raw", "--lang", "sh")
        (root / "tools" / "raw.test").unlink()
        run_tmt(root, "stage", "raw", "stable")  # refused: no test
        write_executable(
            root / "tools" / "raw.test", PASSING_TEST.format(tool_id="raw")
        )

        payload = self.assert_json_success(
            run_tmt(root, "stage", "raw", "stable", "--json")
        )

        self.assertEqual(payload["id"], "raw")
        self.assertEqual(payload["previous"], "draft")
        self.assertEqual(payload["stage"], "stable")
        self.assertTrue(payload["changed"])
        self.assertEqual(
            load_registry(root)["tools"]["raw"]["stage"], "stable"
        )
        returncode, failures, _ = self.check_json(root)
        self.assertEqual((returncode, failures), (0, []))

    def test_promotion_refused_on_failing_test(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "flaky", "--lang", "sh")
        write_executable(root / "tools" / "flaky.test", "#!/bin/sh\nexit 1\n")

        payload = self.assert_json_error(
            run_tmt(root, "stage", "flaky", "stable", "--json"),
            "check-failed",
            3,
        )

        self.assertIn("flaky.test exited 1", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["flaky"]["stage"], "draft"
        )

    def test_promotion_refused_on_draft_dependency(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "top", "--lang", "sh")
        run_tmt(root, "new", "helper", "--lang", "sh")
        data = load_registry(root)
        data["tools"]["top"]["requires"] = ["helper"]
        save_registry(root, data)

        payload = self.assert_json_error(
            run_tmt(root, "stage", "top", "stable", "--json"),
            "check-failed",
            3,
        )

        self.assertIn("draft 'helper'", payload["error"])

    def test_promotion_refused_on_pristine_scaffold_test(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "hollow", "--lang", "sh")
        # tools/hollow.test is exactly what `tmt new` scaffolded.

        payload = self.assert_json_error(
            run_tmt(root, "stage", "hollow", "stable", "--json"),
            "check-failed",
            3,
        )

        self.assertIn("unmodified scaffold", payload["error"])
        self.assertIn("real assertions", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["hollow"]["stage"], "draft"
        )

    def test_promotion_succeeds_after_modifying_the_scaffold_test(
        self,
    ) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "hollow", "--lang", "sh")
        result = run_tmt(root, "stage", "hollow", "stable")
        self.assertEqual(result.returncode, 3)  # refused: pristine scaffold
        test = root / "tools" / "hollow.test"
        test.write_text(
            test.read_text(encoding="utf-8")
            + '"$tool" --json >/dev/null\n',
            encoding="utf-8",
        )

        payload = self.assert_json_success(
            run_tmt(root, "stage", "hollow", "stable", "--json")
        )

        self.assertEqual(payload["stage"], "stable")
        self.assertTrue(payload["changed"])
        returncode, failures, _ = self.check_json(root)
        self.assertEqual((returncode, failures), (0, []))

    def test_human_output_reports_the_transition(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "raw", "--lang", "sh")
        write_executable(
            root / "tools" / "raw.test", PASSING_TEST.format(tool_id="raw")
        )

        result = run_tmt(root, "stage", "raw", "stable")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "raw: draft -> stable\n")


class StageDemoteTest(TmtTestCase):
    def _stable(self, root, tool_id: str) -> None:
        run_tmt(root, "new", tool_id, "--lang", "sh")
        write_executable(
            root / "tools" / f"{tool_id}.test",
            PASSING_TEST.format(tool_id=tool_id),
        )
        result = run_tmt(root, "stage", tool_id, "stable")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_demotion_refused_while_a_stable_tool_requires_it(self) -> None:
        root = self.make_repo()
        self._stable(root, "helper")
        run_tmt(root, "new", "top", "--lang", "sh")
        write_executable(
            root / "tools" / "top.test", PASSING_TEST.format(tool_id="top")
        )
        data = load_registry(root)
        data["tools"]["top"]["requires"] = ["helper"]
        save_registry(root, data)
        result = run_tmt(root, "stage", "top", "stable")
        self.assertEqual(result.returncode, 0, result.stderr)

        payload = self.assert_json_error(
            run_tmt(root, "stage", "helper", "draft", "--json"),
            "check-failed",
            3,
        )

        self.assertIn("top", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["helper"]["stage"], "stable"
        )

    def test_demotion_succeeds_without_stable_dependents(self) -> None:
        root = self.make_repo()
        self._stable(root, "loner")

        payload = self.assert_json_success(
            run_tmt(root, "stage", "loner", "draft", "--json")
        )

        self.assertEqual(payload["previous"], "stable")
        self.assertEqual(payload["stage"], "draft")
        self.assertTrue(payload["changed"])
        self.assertEqual(
            load_registry(root)["tools"]["loner"]["stage"], "draft"
        )


class StageNoOpAndErrorsTest(TmtTestCase):
    def test_no_op_at_requested_stage_succeeds_and_says_so(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "idle", "--lang", "sh")

        payload = self.assert_json_success(
            run_tmt(root, "stage", "idle", "draft", "--json")
        )
        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["previous"], "draft")
        self.assertEqual(payload["stage"], "draft")

        human = run_tmt(root, "stage", "idle", "draft")
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertEqual(human.stdout, "idle already draft\n")

    def test_unknown_tool_reports_not_found(self) -> None:
        root = self.make_repo()

        self.assert_json_error(
            run_tmt(root, "stage", "nope", "stable", "--json"),
            "not-found",
            3,
        )

    def test_invalid_stage_is_a_usage_error(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "idle", "--lang", "sh")

        self.assert_json_error(
            run_tmt(root, "stage", "idle", "frozen", "--json"), "usage", 2
        )

    def test_stage_without_registry_reports_no_registry(self) -> None:
        root = self.make_dir()

        self.assert_json_error(
            run_tmt(root, "stage", "idle", "stable", "--json"),
            "no-registry",
            3,
        )


if __name__ == "__main__":
    unittest.main()

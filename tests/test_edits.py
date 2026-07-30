"""Registry-editing verbs: `tmt rm`, `tmt rename`, `tmt set`.

Every field the gates police must be writable through tmt itself, and no
verb may leave a registry `tmt check` would reject.
"""

from __future__ import annotations

import unittest

from _support import TmtTestCase, load_registry, run_tmt


class RemoveTest(TmtTestCase):
    def test_rm_deletes_the_entry_and_its_files(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        result = run_tmt(root, "rm", "alpha", "--json")
        payload = self.assert_json_success(result)
        self.assertEqual(payload["removed_files"], ["alpha", "alpha.test"])
        self.assertEqual(load_registry(root)["tools"], {})
        self.assertFalse((root / "tools" / "alpha").exists())
        self.assertFalse((root / "tools" / "alpha.test").exists())
        self.assertEqual(self.check_json(root)[0], 0)

    def test_rm_keep_files_unregisters_only(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(root, "rm", "alpha", "--keep-files", "--json")
        )
        self.assertEqual(payload["removed_files"], [])
        self.assertTrue((root / "tools" / "alpha").exists())
        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 1)
        self.assertIn("tools/alpha: file has no tmt.json entry", failures)

    def test_rm_refuses_while_a_dependent_requires_it(self) -> None:
        root = self.make_repo()
        for tool_id in ("base", "user"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "user", "requires", "base").returncode, 0
        )
        result = run_tmt(root, "rm", "base", "--json")
        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("required by user", payload["error"])
        self.assertIn("base", load_registry(root)["tools"])

    def test_rm_unknown_tool_is_not_found(self) -> None:
        root = self.make_repo()
        self.assert_json_error(
            run_tmt(root, "rm", "ghost", "--json"), "not-found", 3
        )

    def test_rm_deletes_a_long_doc_companion(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        (root / "tools" / "alpha.md").write_text("doc\n", encoding="utf-8")
        payload = self.assert_json_success(
            run_tmt(root, "rm", "alpha", "--json")
        )
        self.assertEqual(
            payload["removed_files"], ["alpha", "alpha.md", "alpha.test"]
        )


class RenameTest(TmtTestCase):
    def test_rename_moves_files_and_rewrites_dependents(self) -> None:
        root = self.make_repo()
        for tool_id in ("base", "user"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "user", "requires", "base").returncode, 0
        )
        payload = self.assert_json_success(
            run_tmt(root, "rename", "base", "core", "--json")
        )
        self.assertEqual(payload["previous"], "base")
        self.assertEqual(payload["updated_dependents"], ["user"])
        self.assertEqual(payload["moved_files"], ["core", "core.test"])
        data = load_registry(root)
        self.assertIn("core", data["tools"])
        self.assertNotIn("base", data["tools"])
        self.assertEqual(data["tools"]["user"]["requires"], ["core"])
        self.assertTrue((root / "tools" / "core").exists())
        self.assertFalse((root / "tools" / "base").exists())
        self.assertEqual(self.check_json(root)[0], 0)

    def test_rename_warns_about_a_body_still_calling_the_old_id(self) -> None:
        root = self.make_repo()
        for tool_id in ("leaf", "caller"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        caller = root / "tools" / "caller"
        caller.write_text(
            "#!/bin/sh\n"
            'case "$1" in --help) echo usage; exit 0;; esac\n'
            '"$(dirname "$0")/leaf"\n',
            encoding="utf-8",
        )
        caller.chmod(0o755)
        self.assertEqual(
            run_tmt(root, "set", "caller", "lang", "sh").returncode, 0
        )
        self.assertEqual(
            run_tmt(root, "set", "caller", "requires", "leaf").returncode, 0
        )

        human = run_tmt(root, "rename", "leaf", "leaf2")

        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("caller still calls 'leaf'", human.stdout)
        payload = self.assert_json_success(
            run_tmt(root, "rename", "caller", "caller2", "--json")
        )
        self.assertEqual(payload["stale_callers"], [])

    def test_rename_reports_no_stale_callers_when_none_exist(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(root, "rename", "alpha", "beta", "--json")
        )
        self.assertEqual(payload["stale_callers"], [])

    def test_rename_refuses_an_existing_id(self) -> None:
        root = self.make_repo()
        for tool_id in ("alpha", "beta"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        self.assert_json_error(
            run_tmt(root, "rename", "alpha", "beta", "--json"),
            "already-exists",
            3,
        )
        self.assertIn("alpha", load_registry(root)["tools"])

    def test_rename_refuses_an_invalid_id(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        self.assert_json_error(
            run_tmt(root, "rename", "alpha", "Bad Id", "--json"), "usage", 2
        )

    def test_rename_to_the_same_id_is_a_usage_error(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        self.assert_json_error(
            run_tmt(root, "rename", "alpha", "alpha", "--json"), "usage", 2
        )


class SetTest(TmtTestCase):
    def test_set_text_field_round_trips(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(root, "set", "alpha", "purpose", "Real purpose", "--json")
        )
        self.assertEqual(payload["value"], "Real purpose")
        self.assertEqual(
            load_registry(root)["tools"]["alpha"]["purpose"], "Real purpose"
        )

    def test_set_rejects_a_purpose_over_the_cap(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        result = run_tmt(root, "set", "alpha", "purpose", "x" * 81, "--json")
        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("80-character cap", payload["error"])
        self.assertNotEqual(
            load_registry(root)["tools"]["alpha"]["purpose"], "x" * 81
        )

    def test_set_boolean_field(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(root, "set", "alpha", "mutates", "true", "--json")
        )
        self.assertIs(payload["value"], True)
        self.assertIs(
            load_registry(root)["tools"]["alpha"]["mutates"], True
        )

    def test_set_boolean_rejects_other_words(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        self.assert_json_error(
            run_tmt(root, "set", "alpha", "mutates", "yes", "--json"),
            "usage",
            2,
        )

    def test_set_requires_rejects_an_unregistered_dependency(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        result = run_tmt(root, "set", "alpha", "requires", "ghost", "--json")
        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("not registered", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["alpha"].get("requires", []), []
        )

    def test_set_list_field_splits_on_commas(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(root, "set", "alpha", "config", "a.toml, b.json", "--json")
        )
        self.assertEqual(payload["value"], ["a.toml", "b.json"])

    def test_stage_is_not_settable(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        result = run_tmt(root, "set", "alpha", "stage", "stable", "--json")
        self.assert_json_error(result, "usage", 2)
        self.assertEqual(
            load_registry(root)["tools"]["alpha"]["stage"], "draft"
        )


if __name__ == "__main__":
    unittest.main()

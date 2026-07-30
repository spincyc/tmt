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

    def test_rm_deletes_a_companion_symlink_without_its_target(self) -> None:
        """Unlink never follows, so the link is the repo's to delete.

        Refusing it on containment grounds would make the tool
        unremovable while leaving the link in place.
        """
        outside = self.make_dir()
        planted = outside / "notes.md"
        planted.write_text("outside\n", encoding="utf-8")
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        (root / "tools" / "alpha.md").symlink_to(planted)

        payload = self.assert_json_success(
            run_tmt(root, "rm", "alpha", "--json")
        )

        self.assertEqual(
            payload["removed_files"], ["alpha", "alpha.md", "alpha.test"]
        )
        self.assertFalse((root / "tools" / "alpha.md").is_symlink())
        self.assertEqual(planted.read_text(encoding="utf-8"), "outside\n")
        self.assertEqual(load_registry(root)["tools"], {})
        self.assertEqual(self.check_json(root)[0], 0)

    def test_rm_refuses_a_tools_directory_outside_the_repo(self) -> None:
        outside = self.make_dir()
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        (root / "tools" / "alpha").rename(outside / "alpha")
        (root / "tools" / "alpha.test").rename(outside / "alpha.test")
        (root / "tools").rmdir()
        (root / "tools").symlink_to(outside)

        self.assert_json_error(
            run_tmt(root, "rm", "alpha", "--json"), "containment", 3
        )
        self.assertTrue((outside / "alpha").exists())

    def test_rm_refusal_by_dependent_keeps_the_files(self) -> None:
        root = self.make_repo()
        for tool_id in ("base", "user"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "user", "requires", "base").returncode, 0
        )

        self.assert_json_error(
            run_tmt(root, "rm", "base", "--json"), "check-failed", 3
        )

        self.assertTrue((root / "tools" / "base").exists())
        self.assertTrue((root / "tools" / "base.test").exists())
        self.assertEqual(self.check_json(root)[0], 0)

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

    def test_rename_refusal_moves_nothing(self) -> None:
        """A colliding companion must not leave the executable renamed.

        Moving each file as it was validated renamed `tools/alpha` before
        the `tools/beta.test` collision was noticed, leaving the registry
        pointing at a file that no longer existed.
        """
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        collision = root / "tools" / "beta.test"
        collision.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        result = run_tmt(root, "rename", "alpha", "beta", "--json")

        self.assert_json_error(result, "already-exists", 3)
        self.assertTrue((root / "tools" / "alpha").exists())
        self.assertTrue((root / "tools" / "alpha.test").exists())
        self.assertFalse((root / "tools" / "beta").exists())
        self.assertIn("alpha", load_registry(root)["tools"])
        # A stray companion is not a stray tool, so the repo stays green.
        self.assertEqual(self.check_json(root)[:2], (0, []))

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
        """The refusal must leave the old value, not merely reject the new.

        Asserting only `!= the rejected value` passed for a mutant that
        blanked the field and saved anyway.
        """
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "alpha", "purpose", "Keep me").returncode, 0
        )

        result = run_tmt(root, "set", "alpha", "purpose", "x" * 81, "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("80-character cap", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["alpha"]["purpose"], "Keep me"
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

    def test_set_requires_refuses_a_cycle(self) -> None:
        """`set` must not be able to write what `check` forbids.

        Schema validation alone let a command exit 0 and leave the
        repository red.
        """
        root = self.make_repo()
        for tool_id in ("aa", "bb"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "aa", "requires", "bb").returncode, 0
        )

        result = run_tmt(root, "set", "bb", "requires", "aa", "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("cycle", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["bb"].get("requires", []), []
        )
        self.assertEqual(self.check_json(root)[0], 0)

    def test_set_requires_refuses_a_self_cycle(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "aa").returncode, 0)
        result = run_tmt(root, "set", "aa", "requires", "aa", "--json")
        self.assert_json_error(result, "check-failed", 3)
        self.assertEqual(self.check_json(root)[0], 0)

    def test_set_requires_refuses_a_draft_under_a_stable_tool(self) -> None:
        root = self.make_repo()
        for tool_id in ("cc", "dd"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        test = root / "tools" / "dd.test"
        test.write_text(
            test.read_text(encoding="utf-8") + '"$tool" --help >/dev/null\n',
            encoding="utf-8",
        )
        self.assertEqual(run_tmt(root, "stage", "dd", "stable").returncode, 0)

        result = run_tmt(root, "set", "dd", "requires", "cc", "--json")

        payload = self.assert_json_error(result, "check-failed", 3)
        self.assertIn("would require draft", payload["error"])
        self.assertEqual(self.check_json(root)[0], 0)

    def test_set_list_field_splits_on_commas(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(root, "set", "alpha", "config", "a.toml, b.json", "--json")
        )
        self.assertEqual(payload["value"], ["a.toml", "b.json"])

    def test_set_covers_every_field_type(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        cases: list[tuple[str, str, object]] = [
            ("usage", "tools/alpha [--json]", "tools/alpha [--json]"),
            ("lang", "sh", "sh"),
            ("idempotent", "false", False),
            ("json", "false", False),
        ]
        for field, raw, expected in cases:
            with self.subTest(field=field):
                payload = self.assert_json_success(
                    run_tmt(root, "set", "alpha", field, raw, "--json")
                )
                self.assertEqual(payload["value"], expected)
                self.assertEqual(
                    load_registry(root)["tools"]["alpha"][field], expected
                )

    def test_set_collapses_whitespace_in_text_fields(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        payload = self.assert_json_success(
            run_tmt(
                root, "set", "alpha", "purpose", "  two   words\n", "--json"
            )
        )
        self.assertEqual(payload["value"], "two words")

    def test_set_clears_a_list_field(self) -> None:
        root = self.make_repo()
        for tool_id in ("base", "user"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "user", "requires", "base").returncode, 0
        )

        payload = self.assert_json_success(
            run_tmt(root, "set", "user", "requires", "", "--json")
        )

        self.assertEqual(payload["value"], [])
        self.assertEqual(
            load_registry(root)["tools"]["user"]["requires"], []
        )
        self.assertEqual(self.check_json(root)[0], 0)

    def test_set_requires_rejects_a_malformed_id(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        result = run_tmt(root, "set", "alpha", "requires", "Bad Id", "--json")
        payload = self.assert_json_error(result, "usage", 2)
        self.assertIn("Bad Id", payload["error"])

    def test_set_reports_the_previous_value(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        self.assertEqual(
            run_tmt(root, "set", "alpha", "purpose", "First").returncode, 0
        )
        payload = self.assert_json_success(
            run_tmt(root, "set", "alpha", "purpose", "Second", "--json")
        )
        self.assertEqual(payload["previous"], "First")

    def test_set_unknown_tool_is_not_found(self) -> None:
        root = self.make_repo()
        self.assert_json_error(
            run_tmt(root, "set", "ghost", "purpose", "x", "--json"),
            "not-found",
            3,
        )

    def test_stage_is_not_settable(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        result = run_tmt(root, "set", "alpha", "stage", "stable", "--json")
        payload = self.assert_json_error(result, "usage", 2)
        # Pin the field list: without this the test passes on argparse's
        # `choices` alone and says nothing about the guard it is named for.
        self.assertIn("stage", payload["error"])
        self.assertEqual(
            load_registry(root)["tools"]["alpha"]["stage"], "draft"
        )


if __name__ == "__main__":
    unittest.main()

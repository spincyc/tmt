"""CLI surface tests: init, new, list, show, --version, JSON protocol."""

from __future__ import annotations

import os
import subprocess
import unittest

from _support import TmtTestCase, load_registry, run_tmt


class InitTest(TmtTestCase):
    def test_init_creates_registry_and_prints_stanza(self) -> None:
        root = self.make_dir()

        result = run_tmt(root, "init")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        self.assertIn("tmt.json", result.stdout)
        self.assertIn("tmt new", result.stdout)
        self.assertEqual(
            load_registry(root), {"tools": {}, "v": 1}
        )

    def test_init_json_output(self) -> None:
        root = self.make_dir()

        payload = self.assert_json_success(run_tmt(root, "init", "--json"))

        self.assertEqual(payload["status"], "initialized")
        self.assertEqual(payload["path"], str(root / "tmt.json"))
        self.assertEqual(len(payload["stanza"]), 2)

    def test_init_registry_serialization_contract(self) -> None:
        root = self.make_repo()

        text = (root / "tmt.json").read_text(encoding="utf-8")

        self.assertEqual(text, '{\n  "tools": {},\n  "v": 1\n}\n')

    def test_second_init_reports_already_exists_and_preserves_registry(
        self,
    ) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "keeper")

        result = run_tmt(root, "init", "--json")

        self.assert_json_error(result, "already-exists", 3)
        self.assertIn("keeper", load_registry(root)["tools"])


class NewTest(TmtTestCase):
    def test_new_defaults_to_python(self) -> None:
        root = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(root, "new", "changed-files", "--json")
        )

        self.assertEqual(payload["id"], "changed-files")
        self.assertEqual(payload["lang"], "python")
        self.assertEqual(payload["path"], "tools/changed-files")
        self.assertEqual(payload["stage"], "draft")
        self.assertEqual(payload["test_path"], "tools/changed-files.test")
        tool = root / "tools" / "changed-files"
        body = tool.read_text(encoding="utf-8")
        self.assertTrue(body.startswith("#!/usr/bin/env python3\n"))
        self.assertNotIn("__TOOL_ID__", body)
        entry = load_registry(root)["tools"]["changed-files"]
        self.assertEqual(entry["lang"], "python")
        self.assertEqual(entry["stage"], "draft")

    def test_new_lang_sh(self) -> None:
        root = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(root, "new", "wrapper", "--lang", "sh", "--json")
        )

        self.assertEqual(payload["lang"], "sh")
        body = (root / "tools" / "wrapper").read_text(encoding="utf-8")
        self.assertTrue(body.startswith("#!/bin/sh\n"))
        self.assertEqual(load_registry(root)["tools"]["wrapper"]["lang"], "sh")

    def test_new_records_purpose_and_usage(self) -> None:
        root = self.make_repo()

        run_tmt(
            root,
            "new",
            "greet",
            "--purpose",
            "Say hello",
            "--usage",
            "tools/greet [--json] NAME",
        )

        entry = load_registry(root)["tools"]["greet"]
        self.assertEqual(entry["purpose"], "Say hello")
        self.assertEqual(entry["usage"], "tools/greet [--json] NAME")

    def test_new_scaffolds_born_passing_smoke_test(self) -> None:
        root = self.make_repo()
        for tool_id, lang in (("pytool", "python"), ("shtool", "sh")):
            with self.subTest(lang=lang):
                run_tmt(root, "new", tool_id, "--lang", lang)
                test = root / "tools" / f"{tool_id}.test"

                self.assertTrue(test.is_file())
                self.assertTrue(os.access(test, os.X_OK))
                body = test.read_text(encoding="utf-8")
                self.assertTrue(body.startswith("#!/bin/sh\n"))
                self.assertNotIn("__TOOL_ID__", body)
                completed = subprocess.run(
                    [os.fspath(test)],
                    cwd=os.fspath(root),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_new_human_output_lists_tool_and_test(self) -> None:
        root = self.make_repo()

        result = run_tmt(root, "new", "greet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout, "tools/greet\ntools/greet.test\n"
        )

    def test_new_duplicate_id_reports_already_exists(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "twice")

        result = run_tmt(root, "new", "twice", "--json")

        self.assert_json_error(result, "already-exists", 3)

    def test_new_invalid_id_is_a_usage_error(self) -> None:
        root = self.make_repo()

        result = run_tmt(root, "new", "Bad_Id", "--json")

        self.assert_json_error(result, "usage", 2)

    def test_new_overlong_purpose_is_a_usage_error(self) -> None:
        root = self.make_repo()

        result = run_tmt(
            root, "new", "long", "--purpose", "x" * 81, "--json"
        )

        self.assert_json_error(result, "usage", 2)

    def test_new_without_registry_reports_no_registry(self) -> None:
        root = self.make_dir()

        result = run_tmt(root, "new", "orphan", "--json")

        self.assert_json_error(result, "no-registry", 3)


class ListTest(TmtTestCase):
    def test_list_human_one_line_per_tool(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "beta", "--purpose", "Second tool")
        run_tmt(root, "new", "alpha", "--purpose", "First tool")

        result = run_tmt(root, "list")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "alpha\tdraft\tFirst tool\nbeta\tdraft\tSecond tool\n",
        )

    def test_list_json(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "alpha", "--purpose", "First tool")

        payload = self.assert_json_success(run_tmt(root, "list", "--json"))

        self.assertEqual(
            payload["tools"],
            [{"id": "alpha", "purpose": "First tool", "stage": "draft"}],
        )

    def test_list_without_registry_reports_no_registry(self) -> None:
        root = self.make_dir()

        self.assert_json_error(
            run_tmt(root, "list", "--json"), "no-registry", 3
        )
        human = run_tmt(root, "list")
        self.assertEqual(human.returncode, 3)
        self.assertEqual(human.stdout, "")
        self.assertTrue(human.stderr.startswith("tmt: "), human.stderr)


class ShowTest(TmtTestCase):
    def test_show_json_includes_entry_help_and_doc(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "greet", "--purpose", "Say hello")
        (root / "tools" / "greet.md").write_text(
            "Long-form doc.\n", encoding="utf-8"
        )

        payload = self.assert_json_success(
            run_tmt(root, "show", "greet", "--json")
        )

        self.assertEqual(payload["id"], "greet")
        self.assertEqual(payload["doc"], "Long-form doc.\n")
        self.assertIn("usage:", payload["help"])
        entry = payload["entry"]
        self.assertEqual(entry["purpose"], "Say hello")
        self.assertEqual(entry["stage"], "draft")
        self.assertEqual(entry["lang"], "python")
        self.assertEqual(entry["origin"], "local")
        self.assertEqual(entry["requires"], [])

    def test_show_human_output(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "greet", "--purpose", "Say hello")

        result = run_tmt(root, "show", "greet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("purpose\tSay hello\n", result.stdout)
        self.assertIn("stage\tdraft\n", result.stdout)
        self.assertIn("usage:", result.stdout)  # captured --help output

    def test_show_unknown_tool_reports_not_found(self) -> None:
        root = self.make_repo()

        self.assert_json_error(
            run_tmt(root, "show", "nope", "--json"), "not-found", 3
        )
        human = run_tmt(root, "show", "nope")
        self.assertEqual(human.returncode, 3)
        self.assertEqual(human.stdout, "")
        self.assertTrue(human.stderr.startswith("tmt: "), human.stderr)


class ProtocolTest(TmtTestCase):
    def test_success_is_one_compact_key_sorted_object(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "alpha")

        result = run_tmt(root, "list", "--json")

        # parse_single_json asserts: exactly one line, compact separators,
        # key-sorted serialization, and top-level "v": 1.
        payload = self.assert_json_success(result)
        self.assertIn("tools", payload)

    def test_json_errors_go_to_stderr_with_stable_code(self) -> None:
        root = self.make_repo()

        payload = self.assert_json_error(
            run_tmt(root, "show", "missing", "--json"), "not-found", 3
        )

        self.assertIn("missing", payload["error"])

    def test_corrupt_registry_reports_check_failed(self) -> None:
        root = self.make_repo()
        (root / "tmt.json").write_text("{not json\n", encoding="utf-8")

        self.assert_json_error(
            run_tmt(root, "list", "--json"), "check-failed", 3
        )

    def test_usage_error_exits_2_with_json_on_stderr(self) -> None:
        root = self.make_repo()

        result = run_tmt(root, "bogus-command", "--json")

        self.assert_json_error(result, "usage", 2)

    def test_usage_error_without_json_is_plain_text(self) -> None:
        root = self.make_repo()

        result = run_tmt(root, "bogus-command")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotEqual(result.stderr, "")

    def test_version(self) -> None:
        root = self.make_dir()

        result = run_tmt(root, "--version")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()

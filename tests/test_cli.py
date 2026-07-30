"""CLI surface tests: init, new, list, show, --version, JSON protocol."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from _support import TmtTestCase, load_registry, run_tmt, save_registry

# Repo-supplied text tmt must carry through unchanged: an accent, a CJK
# pair, and an astral emoji, well inside the 80-character purpose cap.
UNICODE_PURPOSE = "Résumé du café ☕ 中文 😀"
# U+E0002 is a TAG character: astral and not printable, so human output
# must escape it — with eight hex digits, never a malformed five.
TAG_CHARACTER = "\U000e0002"
EMOJI = "\U0001f600"


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
        self.assertEqual(entry["config"], [])  # schema default filled in

    def test_show_human_output(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "greet", "--purpose", "Say hello")

        result = run_tmt(root, "show", "greet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("purpose\tSay hello\n", result.stdout)
        self.assertIn("stage\tdraft\n", result.stdout)
        self.assertIn("usage:", result.stdout)  # captured --help output

    def test_show_displays_declared_config(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "budgets", "--purpose", "Scan doc budgets")
        data = load_registry(root)
        data["tools"]["budgets"]["config"] = [
            ".doc-budgets.json",
            "docs/budgets.toml",
        ]
        save_registry(root, data)

        payload = self.assert_json_success(
            run_tmt(root, "show", "budgets", "--json")
        )
        self.assertEqual(
            payload["entry"]["config"],
            [".doc-budgets.json", "docs/budgets.toml"],
        )

        human = run_tmt(root, "show", "budgets")
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn(
            "config\t.doc-budgets.json,docs/budgets.toml\n", human.stdout
        )

    def test_show_escapes_control_characters_from_the_long_doc(self) -> None:
        """tools/<id>.md is repo-supplied text, like the captured --help.

        Human output escapes its control characters so a doc cannot
        repaint the terminal; `--json` escapes them structurally instead,
        so the payload still carries the document verbatim.
        """
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        doc = "docstart\x1b]0;pwned\x07docend\n"
        (root / "tools" / "alpha.md").write_text(doc, encoding="utf-8")

        human = run_tmt(root, "show", "alpha")

        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertNotIn("\x1b", human.stdout)
        self.assertNotIn("\x07", human.stdout)
        self.assertIn(
            "docstart\\u001b]0;pwned\\u0007docend\n", human.stdout
        )

        machine = run_tmt(root, "show", "alpha", "--json")

        payload = self.assert_json_success(machine)
        self.assertEqual(payload["doc"], doc)
        self.assertNotIn("\x1b", machine.stdout)
        self.assertIn("\\u001b", machine.stdout)

    def test_show_human_renders_a_vendored_origin_as_repo_at_commit(
        self,
    ) -> None:
        """`tmt vendor` stamps origin as an object; human output folds it."""
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "vend").returncode, 0)
        origin = {
            "commit": "a" * 40,
            "repo": "/srv/tmt-lib",
            "sha256": "b" * 64,
        }
        data = load_registry(root)
        data["tools"]["vend"]["origin"] = origin
        save_registry(root, data)

        human = run_tmt(root, "show", "vend")

        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn(f"origin\t/srv/tmt-lib@{'a' * 40}\n", human.stdout)
        payload = self.assert_json_success(
            run_tmt(root, "show", "vend", "--json")
        )
        self.assertEqual(payload["entry"]["origin"], origin)

    def test_show_reports_a_non_utf8_doc_as_a_content_failure(self) -> None:
        """A companion doc's bytes are the repo's, not a tmt defect.

        The doc read was the one reader without a decode guard, so it
        escaped to the exit-70 defect boundary.
        """
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        (root / "tools" / "alpha.md").write_bytes(b"ok \xff\xfe\n")

        result = run_tmt(root, "show", "alpha", "--json")

        self.assert_json_error(result, "check-failed", 3)

    def test_show_refuses_a_tool_symlinked_outside_the_repo(self) -> None:
        """show executes the tool, so it needs the same gate as check.

        `tmt check` contained the executable while `tmt show` ran it
        ungated, executing a file the clone does not contain and printing
        a doc from outside the repository.
        """
        outside = self.make_dir()
        marker = outside / "ran"
        planted = outside / "evil"
        planted.write_text(
            "#!/bin/sh\n"
            f'touch "{marker}"\n'
            'case "$1" in --help) echo usage; exit 0;; esac\n',
            encoding="utf-8",
        )
        planted.chmod(0o755)
        secret = outside / "secret.md"
        secret.write_text("SECRET DOC\n", encoding="utf-8")
        root = self.make_repo()
        (root / "tools").mkdir(exist_ok=True)
        (root / "tools" / "st").symlink_to(planted)
        (root / "tools" / "st.md").symlink_to(secret)
        data = load_registry(root)
        data["tools"]["st"] = {
            "purpose": "p",
            "stage": "draft",
            "usage": "u",
            "lang": "sh",
        }
        save_registry(root, data)

        result = run_tmt(root, "show", "st", "--json")

        self.assert_json_error(result, "containment", 3)
        self.assertFalse(marker.exists(), "the outside file was executed")

    def test_show_unknown_tool_reports_not_found(self) -> None:
        root = self.make_repo()

        self.assert_json_error(
            run_tmt(root, "show", "nope", "--json"), "not-found", 3
        )
        human = run_tmt(root, "show", "nope")
        self.assertEqual(human.returncode, 3)
        self.assertEqual(human.stdout, "")
        self.assertTrue(human.stderr.startswith("tmt: "), human.stderr)


class NonAsciiOutputTest(TmtTestCase):
    """cli-v1 JSON is UTF-8: non-ASCII text is never \\uXXXX-escaped."""

    def setUp(self) -> None:
        self.root = self.make_repo()
        result = run_tmt(
            self.root, "new", "greet", "--purpose", UNICODE_PURPOSE
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_list_json_carries_non_ascii_literally(self) -> None:
        result = run_tmt(self.root, "list", "--json")

        payload = self.assert_json_success(result)
        self.assertEqual(
            payload["tools"],
            [{"id": "greet", "purpose": UNICODE_PURPOSE, "stage": "draft"}],
        )
        self.assertIn(UNICODE_PURPOSE, result.stdout)
        self.assertNotIn("\\u", result.stdout)

    def test_show_json_carries_non_ascii_literally(self) -> None:
        result = run_tmt(self.root, "show", "greet", "--json")

        payload = self.assert_json_success(result)
        self.assertEqual(payload["entry"]["purpose"], UNICODE_PURPOSE)
        self.assertIn(f'"purpose":"{UNICODE_PURPOSE}"', result.stdout)
        self.assertNotIn("\\u00", result.stdout)

    def test_check_json_carries_non_ascii_failure_text_literally(
        self,
    ) -> None:
        """check echoes no purpose, so an invalid key is the only route."""
        data = load_registry(self.root)
        data["clé ☕"] = 1
        save_registry(self.root, data)

        result = run_tmt(self.root, "check", "--json")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(len(payload["failures"]), 1, payload["failures"])
        failure = payload["failures"][0]
        self.assertTrue(failure.startswith("registry: "), failure)
        self.assertIn("clé ☕", failure)
        self.assertNotIn("\\u", result.stdout)

    def test_human_output_carries_non_ascii_literally(self) -> None:
        listed = run_tmt(self.root, "list")
        shown = run_tmt(self.root, "show", "greet")

        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(listed.stdout, f"greet\tdraft\t{UNICODE_PURPOSE}\n")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn(f"purpose\t{UNICODE_PURPOSE}\n", shown.stdout)
        self.assertNotIn("\\u", shown.stdout)


class AstralEscapeTest(TmtTestCase):
    """Human output escapes unprintable characters, not printable ones."""

    def _repo_with_purpose(self, purpose: str) -> Path:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        data = load_registry(root)
        data["tools"]["alpha"]["purpose"] = purpose
        save_registry(root, data)
        return root

    def test_unprintable_astral_character_escapes_as_eight_hex_digits(
        self,
    ) -> None:
        root = self._repo_with_purpose(f"tag{TAG_CHARACTER}end")

        shown = run_tmt(root, "show", "alpha")
        listed = run_tmt(root, "list")

        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("purpose\ttag\\U000e0002end\n", shown.stdout)
        self.assertEqual(listed.stdout, "alpha\tdraft\ttag\\U000e0002end\n")
        for output in (shown.stdout, listed.stdout):
            self.assertNotIn(TAG_CHARACTER, output)
            # A five-hex escape was the previous bug: a reader
            # takes it as U+E000 followed by a literal "2".
            self.assertNotIn("\\ue0002", output)

    def test_printable_astral_character_is_passed_through(self) -> None:
        root = self._repo_with_purpose(f"smile{EMOJI}")

        shown = run_tmt(root, "show", "alpha")
        listed = run_tmt(root, "list")

        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn(f"purpose\tsmile{EMOJI}\n", shown.stdout)
        self.assertEqual(listed.stdout, f"alpha\tdraft\tsmile{EMOJI}\n")
        self.assertNotIn("\\U0001f600", shown.stdout)


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

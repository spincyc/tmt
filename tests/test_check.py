"""The tmt check gate battery: born-passing scaffolds and each failure."""

from __future__ import annotations

import hashlib
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import (
    SRC_DIR,
    TmtTestCase,
    load_registry,
    run_tmt,
    save_registry,
    write_executable,
)

# The only module that also drives the battery in process (see
# BatteryInternalsTest), so src/ has to be importable however the suite was
# launched, not only through the PYTHONPATH the Makefile sets.
if os.fspath(SRC_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(SRC_DIR))

from tmt import checks  # noqa: E402

PASSING_TEST = "#!/bin/sh\nset -eu\n\"tools/{tool_id}\" --help >/dev/null\n"
HANGING = "#!/bin/sh\nsleep 30\n"


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

    def test_deeply_nested_registry_is_a_collected_failure(self) -> None:
        root = self.make_repo()
        # json.loads recurses once per level, so this overflows the stack:
        # the battery must collect that as a parse failure.
        (root / "tmt.json").write_text(
            "[" * 100000 + "]" * 100000, encoding="utf-8"
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("registry: tmt.json does not parse", failures[0])

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

    def test_unbounded_help_output_is_capped(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "hog", "--lang", "sh")
        # /dev/zero finishes inside the help timeout, so only a byte cap
        # keeps this from exhausting memory.
        write_executable(
            root / "tools" / "hog", "#!/bin/sh\nexec cat /dev/zero\n"
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            ["hog: --help wrote more than 1048576 bytes to stdout"],
        )


class UngatedLangTest(TmtTestCase):
    """A lang no linter covers is disclosed as a warning, never a failure."""

    def _sh_tool_declaring(self, root: Path, tool_id: str, lang: str) -> None:
        """A working sh tool whose registry entry claims ``lang``."""
        self.assertEqual(
            run_tmt(root, "new", tool_id, "--lang", "sh").returncode, 0
        )
        data = load_registry(root)
        data["tools"][tool_id]["lang"] = lang
        save_registry(root, data)

    def test_unlintable_lang_warns_and_still_exits_zero(self) -> None:
        root = self.make_repo()
        self._sh_tool_declaring(root, "ferrous", "rust")

        returncode, failures, warnings = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))
        self.assertEqual(
            warnings,
            [
                "ferrous: lang 'rust' has no syntax gate; the body was "
                "not linted (gated langs: python, sh)"
            ],
        )

    def test_lang_typo_warns_rather_than_silently_skipping(self) -> None:
        root = self.make_repo()
        self._sh_tool_declaring(root, "typo", "PYTHON")

        result = run_tmt(root, "check")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "WARN typo: lang 'PYTHON' has no syntax gate; the body was "
            "not linted (gated langs: python, sh)\nok\n",
        )

    def test_control_characters_in_lang_are_escaped(self) -> None:
        root = self.make_repo()
        # A registry is repo-supplied: no lang reaches a terminal as a
        # live escape sequence.
        self._sh_tool_declaring(root, "sneaky", "ru\u009bst")

        returncode, failures, warnings = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))
        self.assertEqual(len(warnings), 1, warnings)
        self.assertNotIn("\u009b", warnings[0])
        self.assertIn("'ru\\x9bst'", warnings[0])

    def test_scoped_check_warns_only_about_the_named_tool(self) -> None:
        root = self.make_repo()
        self._sh_tool_declaring(root, "ferrous", "rust")
        self.assertEqual(run_tmt(root, "new", "plain").returncode, 0)

        scoped = self.assert_json_success(
            run_tmt(root, "check", "ferrous", "--json")
        )
        self.assertEqual(len(scoped["warnings"]), 1, scoped)
        self.assertIn("lang 'rust'", scoped["warnings"][0])

        python_tool = self.assert_json_success(
            run_tmt(root, "check", "plain", "--json")
        )
        self.assertEqual(python_tool["warnings"], [])

    def test_promotion_battery_ignores_the_warning(self) -> None:
        root = self.make_repo()
        self._sh_tool_declaring(root, "ferrous", "rust")
        write_executable(
            root / "tools" / "ferrous.test",
            PASSING_TEST.format(tool_id="ferrous"),
        )

        result = run_tmt(root, "stage", "ferrous", "stable")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            load_registry(root)["tools"]["ferrous"]["stage"], "stable"
        )


class StableGateTest(TmtTestCase):
    def _make_stable(self, root, tool_id: str, *, with_test: bool = True):
        run_tmt(root, "new", tool_id, "--lang", "sh")
        test = root / "tools" / f"{tool_id}.test"
        if with_test:
            write_executable(test, PASSING_TEST.format(tool_id=tool_id))
        else:
            test.unlink()  # discard the scaffolded smoke test
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

    def test_stable_with_pristine_scaffold_test_fails(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "hollow", "--lang", "sh")
        # Keep the scaffolded tools/hollow.test untouched; hand-edit the
        # stage so `tmt check` itself exercises the gate.
        data = load_registry(root)
        data["tools"]["hollow"]["stage"] = "stable"
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            [
                "hollow: tools/hollow.test is the unmodified scaffold; "
                "write real assertions before promoting"
            ],
        )

    def test_stable_test_without_the_executable_bit(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "unarmed")
        (root / "tools" / "unarmed.test").chmod(0o644)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            ["unarmed: executable bit not set on tools/unarmed.test"],
        )

    def test_stable_failing_test(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "flaky")
        write_executable(root / "tools" / "flaky.test", "#!/bin/sh\nexit 1\n")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(failures, ["flaky: tools/flaky.test exited 1"])

    def test_symlinked_test_outside_the_repo_is_refused(self) -> None:
        root = self.make_repo()
        self._make_stable(root, "st")
        outside = self.make_dir()
        proof = outside / "PROOF"
        evil = outside / "evil.test"
        write_executable(evil, f'#!/bin/sh\n: > "{proof}"\n')
        test = root / "tools" / "st.test"
        test.unlink()
        test.symlink_to(evil)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("st: tools/st.test", failures[0])
        self.assertIn("outside the repository", failures[0])
        self.assertFalse(proof.exists())

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


class CompositionGateTest(TmtTestCase):
    """Using a sibling tool without declaring it in requires is a failure."""

    def _compose(self, root, caller: str, callee: str) -> None:
        run_tmt(root, "new", caller, "--lang", "sh")
        run_tmt(root, "new", callee, "--lang", "sh")
        tool = root / "tools" / caller
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + f'"$(dirname "$0")/{callee}" --json >/dev/null\n',
            encoding="utf-8",
        )

    def test_undeclared_sibling_use_fails_for_drafts(self) -> None:
        root = self.make_repo()
        self._compose(root, "affected-tests", "changed-files")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            [
                "affected-tests: uses sibling 'changed-files' without "
                "declaring it in requires"
            ],
        )

    def test_declared_sibling_use_passes(self) -> None:
        root = self.make_repo()
        self._compose(root, "affected-tests", "changed-files")
        data = load_registry(root)
        data["tools"]["affected-tests"]["requires"] = ["changed-files"]
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))

    def test_sibling_mention_in_full_line_comment_is_exempt(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "doc-budgets", "--lang", "sh")
        run_tmt(root, "new", "doc-scan", "--lang", "sh")
        tool = root / "tools" / "doc-scan"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + "  # Sibling doc-budgets composes this tool\n",
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))

    def test_a_sibling_named_in_prose_is_not_a_call(self) -> None:
        """Only a path position counts, wherever the words appear.

        Matching the bare word made a tool named after an ordinary word
        fail against that word in every other tool, which no declaration
        could fix — see test_a_tool_named_after_a_common_word.
        """
        root = self.make_repo()
        run_tmt(root, "new", "doc-budgets", "--lang", "sh")
        run_tmt(root, "new", "doc-scan", "--lang", "sh")
        tool = root / "tools" / "doc-scan"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + "printf '%s\\n' 'Sibling doc-budgets composes this tool'\n",
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))

    def test_a_path_position_in_a_string_still_fails(self) -> None:
        """Path strings are why string literals are scanned at all."""
        root = self.make_repo()
        run_tmt(root, "new", "doc-budgets", "--lang", "sh")
        run_tmt(root, "new", "doc-scan", "--lang", "sh")
        tool = root / "tools" / "doc-scan"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + 'target="tools/doc-budgets"\n',
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(
            failures,
            [
                "doc-scan: uses sibling 'doc-budgets' without declaring "
                "it in requires"
            ],
        )

    def test_a_tool_named_after_a_common_word(self) -> None:
        """A plausible id must not be unusable.

        The scaffold's own text contains the word "json", so matching the
        bare word made `tmt new json` fail every other tool in the repo.
        """
        root = self.make_repo()
        run_tmt(root, "new", "json", "--lang", "sh")
        run_tmt(root, "new", "other", "--lang", "sh")

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))

    def test_undecodable_body_is_skipped_not_a_crash(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "caller", "--lang", "sh")
        run_tmt(root, "new", "callee", "--lang", "sh")
        tool = root / "tools" / "caller"
        # The same sibling reference in a decodable body is a failure
        # (test_undeclared_sibling_use_fails_for_drafts); undecodable, the
        # gate has nothing to scan and the battery must still finish.
        tool.write_bytes(
            tool.read_bytes() + b'test "$0" = callee || : "\xff\xfe"\n'
        )

        result = run_tmt(root, "check", "--json")
        payload = self.parse_single_json(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(payload["failures"], [])

    def test_id_embedded_in_longer_identifier_does_not_match(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "files", "--lang", "sh")
        run_tmt(root, "new", "lister", "--lang", "sh")
        tool = root / "tools" / "lister"
        tool.write_text(
            tool.read_text(encoding="utf-8")
            + "# consumes changed-files output only\n"
            + "changed_files=1\n",
            encoding="utf-8",
        )

        returncode, failures, _ = self.check_json(root)

        self.assertEqual((returncode, failures), (0, []))


class ConfigFieldTest(TmtTestCase):
    """The optional `config` field validates and round-trips."""

    def test_config_validates_and_round_trips(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "budgets", "--lang", "sh")
        data = load_registry(root)
        data["tools"]["budgets"]["config"] = [".doc-budgets.json"]
        save_registry(root, data)

        returncode, failures, warnings = self.check_json(root)

        self.assertEqual((returncode, failures, warnings), (0, [], []))
        self.assertEqual(
            load_registry(root)["tools"]["budgets"]["config"],
            [".doc-budgets.json"],
        )

    def test_config_must_be_an_array(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "budgets", "--lang", "sh")
        data = load_registry(root)
        data["tools"]["budgets"]["config"] = ".doc-budgets.json"
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("config", failures[0])
        self.assertIn("array", failures[0])

    def test_config_items_must_be_nonempty_unique_strings(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "budgets", "--lang", "sh")
        data = load_registry(root)
        data["tools"]["budgets"]["config"] = ["", 7, "a.json", "a.json"]
        save_registry(root, data)

        returncode, failures, _ = self.check_json(root)

        self.assertEqual(returncode, 1)
        self.assertEqual(len(failures), 3, failures)
        self.assertIn("config[0]", failures[0])
        self.assertIn("config[1]", failures[1])
        self.assertIn("duplicate", failures[2])


class ScopedCheckTest(TmtTestCase):
    """`tmt check ID` gates one tool and runs nothing else."""

    def _marker_tool(self, root: Path, tool_id: str) -> Path:
        """A registered sh tool that records the fact it was executed."""
        self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        marker = root / f"{tool_id}.ran"
        write_executable(
            root / "tools" / tool_id,
            "#!/bin/sh\n"
            f'touch "$(dirname "$0")/../{tool_id}.ran"\n'
            'case "$1" in --help) echo usage; exit 0;; esac\n',
        )
        self.assertEqual(
            run_tmt(root, "set", tool_id, "lang", "sh").returncode, 0
        )
        return marker

    def test_scoped_check_executes_only_the_named_tool(self) -> None:
        root = self.make_repo()
        named = self._marker_tool(root, "alpha")
        other = self._marker_tool(root, "beta")
        named.unlink(missing_ok=True)
        other.unlink(missing_ok=True)

        result = run_tmt(root, "check", "alpha", "--json")

        payload = self.assert_json_success(result)
        self.assertEqual(payload["id"], "alpha")
        self.assertEqual(payload["failures"], [])
        self.assertTrue(named.exists(), "the named tool was not run")
        self.assertFalse(other.exists(), "an unnamed tool was executed")

    def test_scoped_check_ignores_another_tools_failure(self) -> None:
        root = self.make_repo()
        for tool_id in ("alpha", "beta"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        (root / "tools" / "beta").unlink()

        scoped = run_tmt(root, "check", "alpha", "--json")
        self.assert_json_success(scoped)

        whole = run_tmt(root, "check", "--json")
        self.assertEqual(whole.returncode, 1)
        self.assertTrue(self.parse_single_json(whole.stdout)["failures"])

    def test_scoped_check_reports_its_own_failure(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        (root / "tools" / "alpha").chmod(0o644)

        result = run_tmt(root, "check", "alpha", "--json")

        self.assertEqual(result.returncode, 1)
        payload = self.parse_single_json(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertTrue(
            any("executable bit" in failure for failure in payload["failures"]),
            payload["failures"],
        )

    def test_scoped_check_reports_its_own_unresolved_requires(self) -> None:
        root = self.make_repo()
        self.assertEqual(run_tmt(root, "new", "alpha").returncode, 0)
        data = load_registry(root)
        data["tools"]["alpha"]["requires"] = ["ghost"]
        save_registry(root, data)

        result = run_tmt(root, "check", "alpha", "--json")

        self.assertEqual(result.returncode, 1)
        payload = self.parse_single_json(result.stdout)
        self.assertTrue(
            any("ghost" in failure for failure in payload["failures"]),
            payload["failures"],
        )

    def test_scoped_check_of_an_unknown_tool_is_not_found(self) -> None:
        root = self.make_repo()
        self.assert_json_error(
            run_tmt(root, "check", "ghost", "--json"), "not-found", 3
        )

    def test_whole_repo_check_payload_has_no_id(self) -> None:
        root = self.make_repo()
        payload = self.assert_json_success(run_tmt(root, "check", "--json"))
        self.assertNotIn("id", payload)


class ListFilterTest(TmtTestCase):
    def _repo_with_both_stages(self) -> Path:
        root = self.make_repo()
        for tool_id in ("alpha", "beta"):
            self.assertEqual(run_tmt(root, "new", tool_id).returncode, 0)
        (root / "tools" / "alpha.test").write_text(
            PASSING_TEST.format(tool_id="alpha"), encoding="utf-8"
        )
        (root / "tools" / "alpha.test").chmod(0o755)
        self.assertEqual(
            run_tmt(root, "stage", "alpha", "stable").returncode, 0
        )
        return root

    def test_stage_filter_selects_one_stage(self) -> None:
        root = self._repo_with_both_stages()

        stable = self.assert_json_success(
            run_tmt(root, "list", "--stage", "stable", "--json")
        )
        self.assertEqual([row["id"] for row in stable["tools"]], ["alpha"])

        draft = self.assert_json_success(
            run_tmt(root, "list", "--stage", "draft", "--json")
        )
        self.assertEqual([row["id"] for row in draft["tools"]], ["beta"])

    def test_unfiltered_list_shows_both(self) -> None:
        root = self._repo_with_both_stages()
        payload = self.assert_json_success(run_tmt(root, "list", "--json"))
        self.assertEqual(
            [row["id"] for row in payload["tools"]], ["alpha", "beta"]
        )

    def test_stage_filter_human_output(self) -> None:
        root = self._repo_with_both_stages()
        result = run_tmt(root, "list", "--stage", "draft")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertTrue(result.stdout.startswith("beta\tdraft\t"))

    def test_unknown_stage_is_a_usage_error(self) -> None:
        root = self.make_repo()
        self.assert_json_error(
            run_tmt(root, "list", "--stage", "retired", "--json"), "usage", 2
        )


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


class BatteryInternalsTest(TmtTestCase):
    """Gates no subprocess run can reach cheaply or observably.

    The battery is called in process here so a deadline constant can be
    shortened: through the CLI these paths cost the real 5s and 60s. The
    ``sha256_file`` refusals are unobservable from outside as well, because
    ``_origin_drift`` turns every OSError into "no drift".
    """

    def test_help_timeout_is_a_failure(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "hang", "--lang", "sh")
        tool = root / "tools" / "hang"
        write_executable(tool, HANGING)

        with mock.patch.object(checks, "HELP_TIMEOUT_SECONDS", 1):
            ok, detail = checks.capture_help(tool)

        self.assertFalse(ok)
        self.assertEqual(detail, "--help did not finish within 1s")

    def test_timed_out_tool_loses_its_descendants(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "spawner", "--lang", "sh")
        marker = root / "descendant.marker"
        # The background child rewrites the marker forever, so deleting it
        # after the timeout and finding it still gone proves the whole
        # process group died rather than only the tool itself.
        write_executable(
            root / "tools" / "spawner",
            "#!/bin/sh\n"
            f'while : ; do : > "{marker}"; sleep 0.05; done &\n'
            "sleep 30\n",
        )

        with mock.patch.object(checks, "HELP_TIMEOUT_SECONDS", 1):
            ok, _ = checks.capture_help(root / "tools" / "spawner")

        self.assertFalse(ok)
        self.assertTrue(marker.exists(), "the descendant never started")
        marker.unlink()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            self.assertFalse(
                marker.exists(), "an orphaned descendant kept running"
            )
            time.sleep(0.05)

    def test_stable_test_timeout_is_a_failure(self) -> None:
        root = self.make_repo()
        run_tmt(root, "new", "slow", "--lang", "sh")
        write_executable(root / "tools" / "slow.test", HANGING)
        data = load_registry(root)
        data["tools"]["slow"]["stage"] = "stable"
        save_registry(root, data)

        with mock.patch.object(checks, "TEST_TIMEOUT_SECONDS", 1):
            failures, warnings = checks.run_checks(root)

        self.assertEqual(
            failures, ["slow: tools/slow.test did not finish within 1s"]
        )
        self.assertEqual(warnings, [])

    def test_sha256_refuses_a_non_regular_file(self) -> None:
        directory = self.make_dir()

        with self.assertRaises(OSError) as caught:
            checks.sha256_file(directory)

        self.assertIn("is not a regular file", str(caught.exception))

    def test_sha256_refuses_a_file_past_the_cap(self) -> None:
        oversized = self.make_dir() / "big"
        body = b"x" * 4096
        oversized.write_bytes(body)
        # The same file under the real cap hashes normally: the shortened
        # cap is what the refusal turns on, not the file itself.
        self.assertEqual(
            checks.sha256_file(oversized), hashlib.sha256(body).hexdigest()
        )

        with mock.patch.object(checks, "SHA256_MAX_BYTES", 1024):
            with self.assertRaises(OSError) as caught:
                checks.sha256_file(oversized)

        self.assertIn("exceeds the 1024-byte hash cap", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

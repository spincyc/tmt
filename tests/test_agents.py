"""The AGENTS.md habit fragment: print, status, write, init, check gate.

The fragment text and the marker grammar are contracts, so the expected
bytes are pinned here verbatim rather than imported from the source.
"""

from __future__ import annotations

import unittest

from _support import TmtTestCase, run_tmt

EXPECTED_FRAGMENT = (
    "Before writing any script, read tmt.json and prefer a listed tool\n"
    "(`tools/<id> --help`). After deriving anything repeatable, run\n"
    "`tmt note <slug>`; at two notes build it with `tmt new <slug>`.\n"
    "Keep the registry honest with `tmt check`."
)
BEGIN_MARKER = "<!-- tmt:agents v1 -->"
END_MARKER = "<!-- /tmt:agents -->"
BLOCK = f"{BEGIN_MARKER}\n{EXPECTED_FRAGMENT}\n{END_MARKER}"
STALE_BLOCK = f"{BEGIN_MARKER}\ntampered text\n{END_MARKER}"
STALE_FAILURE = "AGENTS.md tmt fragment is stale; run `tmt agents --write`"
# Line terminators to str.splitlines, ordinary text to tmt's locator.
EXOTIC_BREAKS = "\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"


class FragmentPrintTest(TmtTestCase):
    def test_human_prints_exact_fragment(self) -> None:
        root = self.make_dir()

        result = run_tmt(root, "integration", "print", "agents")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, EXPECTED_FRAGMENT + "\n")
        self.assertEqual(result.stderr, "")

    def test_json_carries_fragment_and_version(self) -> None:
        root = self.make_dir()

        payload = self.assert_json_success(
            run_tmt(root, "integration", "print", "agents", "--json")
        )

        self.assertEqual(
            payload,
            {"fragment": EXPECTED_FRAGMENT, "fragment_version": 1, "v": 1},
        )

    def test_fragment_stays_within_the_word_cap(self) -> None:
        self.assertLessEqual(len(EXPECTED_FRAGMENT.split()), 50)


class AgentsStatusTest(TmtTestCase):
    def test_no_agents_file(self) -> None:
        root = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--json")
        )

        self.assertEqual(payload["status"], "no-agents-file")
        self.assertEqual(payload["fragment_version"], 1)
        self.assertEqual(payload["path"], str(root / "AGENTS.md"))

    def test_absent_when_file_has_no_markers(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text("# Repo\n", encoding="utf-8")

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--json")
        )

        self.assertEqual(payload["status"], "absent")

    def test_installed_after_write(self) -> None:
        root = self.make_repo()
        run_tmt(root, "agents", "--write")

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--json")
        )

        self.assertEqual(payload["status"], "installed")

    def test_stale_when_block_content_differs(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text(STALE_BLOCK + "\n", encoding="utf-8")

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--json")
        )

        self.assertEqual(payload["status"], "stale")

    def test_human_prints_the_status_word(self) -> None:
        root = self.make_repo()

        result = run_tmt(root, "agents")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "no-agents-file\n")

    def test_without_registry_reports_no_registry(self) -> None:
        root = self.make_dir()

        self.assert_json_error(
            run_tmt(root, "agents", "--json"), "no-registry", 3
        )


class AgentsWriteTest(TmtTestCase):
    def test_creates_missing_file(self) -> None:
        root = self.make_repo()

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--write", "--json")
        )

        self.assertEqual(payload["changed"], True)
        self.assertEqual(payload["previous"], "no-agents-file")
        self.assertEqual(payload["status"], "installed")
        self.assertEqual(
            (root / "AGENTS.md").read_text(encoding="utf-8"), BLOCK + "\n"
        )

    def test_appends_with_blank_line_separator(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text("# Repo\nGuidance.\n", encoding="utf-8")

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--write", "--json")
        )

        self.assertEqual(payload["previous"], "absent")
        self.assertEqual(
            (root / "AGENTS.md").read_text(encoding="utf-8"),
            "# Repo\nGuidance.\n\n" + BLOCK + "\n",
        )

    def test_appends_after_adding_missing_trailing_newline(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text("# Repo", encoding="utf-8")

        run_tmt(root, "agents", "--write")

        self.assertEqual(
            (root / "AGENTS.md").read_text(encoding="utf-8"),
            "# Repo\n\n" + BLOCK + "\n",
        )

    def test_rewrite_is_idempotent(self) -> None:
        root = self.make_repo()
        run_tmt(root, "agents", "--write")
        before = (root / "AGENTS.md").read_bytes()

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--write", "--json")
        )

        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["previous"], "installed")
        self.assertEqual((root / "AGENTS.md").read_bytes(), before)

    def test_replaces_stale_block_in_place(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text(
            f"# Repo\n\n{STALE_BLOCK}\n\nTrailing prose.\n", encoding="utf-8"
        )

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--write", "--json")
        )

        self.assertEqual(payload["changed"], True)
        self.assertEqual(payload["previous"], "stale")
        self.assertEqual(
            (root / "AGENTS.md").read_text(encoding="utf-8"),
            f"# Repo\n\n{BLOCK}\n\nTrailing prose.\n",
        )

    def test_exotic_line_breaks_do_not_move_the_block(self) -> None:
        root = self.make_repo()
        prose = (
            f"# Guide{EXOTIC_BREAKS}{BEGIN_MARKER}{EXOTIC_BREAKS}KEEP ME"
            f"{EXOTIC_BREAKS}{END_MARKER}"
        )
        (root / "AGENTS.md").write_text(
            f"{prose}\n{STALE_BLOCK}\n", encoding="utf-8"
        )

        payload = self.assert_json_success(
            run_tmt(root, "agents", "--write", "--json")
        )

        self.assertEqual(payload["previous"], "stale")
        self.assertEqual(
            (root / "AGENTS.md").read_text(encoding="utf-8"),
            f"{prose}\n{BLOCK}\n",
        )
        self.assertEqual(self.check_json(root)[0], 0)
        again = self.assert_json_success(
            run_tmt(root, "agents", "--write", "--json")
        )
        self.assertEqual(again["changed"], False)

    def test_malformed_block_refuses_write(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text(
            f"{BEGIN_MARKER}\nno end marker\n", encoding="utf-8"
        )

        result = run_tmt(root, "agents", "--write", "--json")

        self.assert_json_error(result, "check-failed", 3)


class InitAgentsTest(TmtTestCase):
    def test_init_agents_installs_the_block(self) -> None:
        root = self.make_dir()

        payload = self.assert_json_success(
            run_tmt(root, "init", "--agents", "--json")
        )

        self.assertEqual(payload["status"], "initialized")
        self.assertEqual(payload["agents"]["status"], "installed")
        self.assertEqual(payload["agents"]["changed"], True)
        self.assertEqual(
            (root / "AGENTS.md").read_text(encoding="utf-8"), BLOCK + "\n"
        )

    def test_init_agents_human_output(self) -> None:
        root = self.make_dir()

        result = run_tmt(root, "init", "--agents")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[-1], "AGENTS.md: installed"
        )


class AgentsCheckGateTest(TmtTestCase):
    def test_installed_block_passes(self) -> None:
        root = self.make_repo()
        run_tmt(root, "agents", "--write")

        code, failures, _ = self.check_json(root)

        self.assertEqual(code, 0, failures)
        self.assertEqual(failures, [])

    def test_missing_file_and_missing_markers_are_not_failures(self) -> None:
        root = self.make_repo()

        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 0, failures)

        (root / "AGENTS.md").write_text("# Repo\n", encoding="utf-8")
        code, failures, _ = self.check_json(root)
        self.assertEqual(code, 0, failures)

    def test_stale_block_fails_with_the_stable_message(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text(STALE_BLOCK + "\n", encoding="utf-8")

        code, failures, _ = self.check_json(root)

        self.assertEqual(code, 1)
        self.assertIn(STALE_FAILURE, failures)

    def test_malformed_block_fails(self) -> None:
        root = self.make_repo()
        (root / "AGENTS.md").write_text(
            f"{BEGIN_MARKER}\nno end marker\n", encoding="utf-8"
        )

        code, failures, _ = self.check_json(root)

        self.assertEqual(code, 1)
        self.assertTrue(
            any("malformed" in failure for failure in failures), failures
        )


if __name__ == "__main__":
    unittest.main()

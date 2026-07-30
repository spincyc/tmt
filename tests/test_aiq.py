"""note/candidates: local store first, aiq as an optional mirror.

The loop must work with no aiq installed, so the local store is what
counting reads. When aiq *is* on PATH, each note is also mirrored to it
through the CLI only; a fake aiq stub placed first on PATH records argv
and stdin so the v1 event envelope can still be asserted exactly, and a
mirroring failure must never fail the note.
"""

from __future__ import annotations

import json
import os
import unittest

from _support import TmtTestCase, run_git, run_tmt, write_aiq_stub

INGEST_RESPONSE = '{"created":true,"message_id":"msg-1","v":1}\n'


class AiqStubTestCase(TmtTestCase):
    def setUp(self) -> None:
        self.repo = self.make_repo()
        self.bin_dir = self.make_dir()
        self.capture_dir = self.make_dir()
        self.env = {
            "PATH": f"{os.fspath(self.bin_dir)}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        }
        self.without_aiq = {"PATH": os.fspath(self.bin_dir)}

    def captured_argvs(self) -> list[list[str]]:
        """Every aiq invocation's argv, in call order."""
        lines = (
            (self.capture_dir / "argv.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        return [json.loads(line) for line in lines]

    def captured_stdin(self) -> str:
        return (self.capture_dir / "stdin.txt").read_text(encoding="utf-8")


class NoteMirrorTest(AiqStubTestCase):
    def test_note_mirrors_the_v1_envelope_to_aiq_ingest(self) -> None:
        write_aiq_stub(
            self.bin_dir, self.capture_dir, {"ingest": INGEST_RESPONSE}
        )

        payload = self.assert_json_success(
            run_tmt(
                self.repo,
                "note",
                "changed-files",
                "--note",
                "re-derived the diff list again",
                "--json",
                env=self.env,
            )
        )

        self.assertEqual(payload["message_id"], "msg-1")
        self.assertEqual(payload["slug"], "changed-files")
        self.assertEqual(payload["count"], 1)
        self.assertIs(payload["recorded"], True)
        self.assertEqual(
            self.captured_argvs()[0],
            ["ingest", "--event-json", "-", "--json"],
        )
        envelope = json.loads(self.captured_stdin())
        self.assertEqual(
            sorted(envelope), ["content", "cwd", "source", "v"]
        )
        self.assertEqual(envelope["v"], 1)
        self.assertEqual(envelope["source"], "tmt")
        self.assertEqual(envelope["cwd"], os.fspath(self.repo))
        self.assertEqual(
            json.loads(envelope["content"]),
            {
                "kind": "tmt-note",
                "note": "re-derived the diff list again",
                "slug": "changed-files",
            },
        )

    def test_note_invalid_slug_is_a_usage_error(self) -> None:
        write_aiq_stub(
            self.bin_dir, self.capture_dir, {"ingest": INGEST_RESPONSE}
        )

        result = run_tmt(
            self.repo, "note", "Bad_Slug", "--json", env=self.env
        )

        self.assert_json_error(result, "usage", 2)
        self.assertFalse((self.capture_dir / "argv.jsonl").exists())

    def test_note_succeeds_when_aiq_mirroring_fails(self) -> None:
        write_aiq_stub(
            self.bin_dir,
            self.capture_dir,
            {"ingest": INGEST_RESPONSE},
            exit_code=1,
        )

        payload = self.assert_json_success(
            run_tmt(
                self.repo, "note", "changed-files", "--json", env=self.env
            )
        )

        self.assertIsNone(payload["message_id"])
        self.assertEqual(payload["count"], 1)
        self.assertIs(payload["recorded"], True)


class NoteWithoutAiqTest(AiqStubTestCase):
    """The whole loop, with no aiq anywhere on PATH."""

    def test_note_records_locally_and_counts(self) -> None:
        first = self.assert_json_success(
            run_tmt(
                self.repo,
                "note",
                "changed-files",
                "--json",
                env=self.without_aiq,
            )
        )
        self.assertEqual(first["count"], 1)
        self.assertIsNone(first["message_id"])

        second = self.assert_json_success(
            run_tmt(
                self.repo,
                "note",
                "changed-files",
                "--json",
                env=self.without_aiq,
            )
        )
        self.assertEqual(second["count"], 2)

    def test_human_suggests_new_at_threshold(self) -> None:
        run_tmt(self.repo, "note", "changed-files", env=self.without_aiq)
        result = run_tmt(
            self.repo, "note", "changed-files", env=self.without_aiq
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "2 notes for 'changed-files' — consider "
            "`tmt new changed-files`\n",
        )

    def test_human_below_threshold_counts_without_suggestion(self) -> None:
        result = run_tmt(
            self.repo, "note", "changed-files", env=self.without_aiq
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "1 note for 'changed-files'\n")

    def test_notes_live_in_git_internal_state_not_the_work_tree(self) -> None:
        run_git(self.repo, "init", "-q", "-b", "main")
        run_tmt(self.repo, "note", "changed-files", env=self.without_aiq)

        self.assertTrue((self.repo / ".git" / "tmt" / "notes.jsonl").is_file())
        in_work_tree = sorted(
            item.name
            for item in self.repo.iterdir()
            if item.name != ".git"
        )
        self.assertEqual(in_work_tree, ["tmt.json"])

    def test_note_for_an_existing_tool_reports_it_is_built(self) -> None:
        self.assertEqual(run_tmt(self.repo, "new", "alpha").returncode, 0)

        payload = self.assert_json_success(
            run_tmt(
                self.repo, "note", "alpha", "--json", env=self.without_aiq
            )
        )

        self.assertIs(payload["built"], True)
        self.assertIs(payload["recorded"], False)
        rows = self.assert_json_success(
            run_tmt(self.repo, "candidates", "--json", env=self.without_aiq)
        )["candidates"]
        self.assertEqual(rows, [])


class CandidatesTest(AiqStubTestCase):
    def _note(self, slug: str, note_text: str | None = None) -> None:
        arguments = ["note", slug]
        if note_text is not None:
            arguments += ["--note", note_text]
        result = run_tmt(self.repo, *arguments, env=self.without_aiq)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_candidates_groups_and_counts_notes(self) -> None:
        self._note("foo")
        self._note("foo", "seen it again")
        self._note("bar")

        payload = self.assert_json_success(
            run_tmt(self.repo, "candidates", "--json", env=self.without_aiq)
        )

        self.assertEqual(
            payload["candidates"],
            [
                {
                    "built": False,
                    "count": 2,
                    "notes": ["seen it again"],
                    "slug": "foo",
                },
                {"built": False, "count": 1, "notes": [], "slug": "bar"},
            ],
        )

    def test_candidates_human_output(self) -> None:
        self._note("foo")
        self._note("foo")
        self._note("bar")

        result = run_tmt(self.repo, "candidates", env=self.without_aiq)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2\tfoo\n1\tbar\n")

    def test_candidates_marks_a_slug_that_became_a_tool(self) -> None:
        self._note("foo")
        self.assertEqual(run_tmt(self.repo, "new", "foo").returncode, 0)

        payload = self.assert_json_success(
            run_tmt(self.repo, "candidates", "--json", env=self.without_aiq)
        )

        self.assertEqual(payload["candidates"][0]["built"], True)
        human = run_tmt(self.repo, "candidates", env=self.without_aiq)
        self.assertEqual(human.stdout, "1\tfoo\tbuilt\n")

    def test_candidates_dismiss_forgets_a_slug(self) -> None:
        self._note("foo")
        self._note("foo")
        self._note("bar")

        payload = self.assert_json_success(
            run_tmt(
                self.repo,
                "candidates",
                "--dismiss",
                "foo",
                "--json",
                env=self.without_aiq,
            )
        )

        self.assertEqual(payload["dismissed"], 2)
        remaining = self.assert_json_success(
            run_tmt(self.repo, "candidates", "--json", env=self.without_aiq)
        )["candidates"]
        self.assertEqual([row["slug"] for row in remaining], ["bar"])

    def test_candidates_is_empty_without_notes(self) -> None:
        payload = self.assert_json_success(
            run_tmt(self.repo, "candidates", "--json", env=self.without_aiq)
        )
        self.assertEqual(payload["candidates"], [])


if __name__ == "__main__":
    unittest.main()

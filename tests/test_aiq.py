"""note/candidates against a fake aiq stub placed first on PATH.

The bridge shells out to the aiq CLI only; the stub records argv and stdin
so the v1 event envelope can be asserted exactly.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from _support import TmtTestCase, run_tmt, write_aiq_stub

INGEST_RESPONSE = '{"created":true,"message_id":"msg-1","v":1}\n'


def _inbox_response(messages: list[dict[str, str]]) -> str:
    return json.dumps({"messages": messages, "v": 1}) + "\n"


def _note_message(slug: str, note: str | None = None) -> dict[str, str]:
    return {
        "source": "tmt",
        "content": json.dumps(
            {"kind": "tmt-note", "note": note, "slug": slug},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


class AiqStubTestCase(TmtTestCase):
    def setUp(self) -> None:
        self.repo = self.make_repo()
        self.bin_dir = self.make_dir()
        self.capture_dir = self.make_dir()
        self.env = {
            "PATH": f"{os.fspath(self.bin_dir)}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        }

    def captured_argv(self) -> list[str]:
        return json.loads(
            (self.capture_dir / "argv.json").read_text(encoding="utf-8")
        )

    def captured_stdin(self) -> str:
        return (self.capture_dir / "stdin.txt").read_text(encoding="utf-8")


class NoteTest(AiqStubTestCase):
    def test_note_passes_v1_envelope_to_aiq_ingest(self) -> None:
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

        self.assertEqual(payload["created"], True)
        self.assertEqual(payload["message_id"], "msg-1")
        self.assertEqual(payload["slug"], "changed-files")
        self.assertEqual(
            self.captured_argv(), ["ingest", "--event-json", "-", "--json"]
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

    def test_note_human_prints_message_id(self) -> None:
        write_aiq_stub(
            self.bin_dir, self.capture_dir, {"ingest": INGEST_RESPONSE}
        )

        result = run_tmt(self.repo, "note", "changed-files", env=self.env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "msg-1\n")

    def test_note_invalid_slug_is_a_usage_error(self) -> None:
        write_aiq_stub(
            self.bin_dir, self.capture_dir, {"ingest": INGEST_RESPONSE}
        )

        result = run_tmt(
            self.repo, "note", "Bad_Slug", "--json", env=self.env
        )

        self.assert_json_error(result, "usage", 2)
        self.assertFalse((self.capture_dir / "argv.json").exists())

    def test_note_when_aiq_is_absent(self) -> None:
        result = run_tmt(
            self.repo,
            "note",
            "changed-files",
            "--json",
            env={"PATH": os.fspath(self.bin_dir)},  # empty dir, no aiq
        )

        self.assert_json_error(result, "aiq-unavailable", 3)

    def test_note_when_aiq_fails(self) -> None:
        write_aiq_stub(
            self.bin_dir,
            self.capture_dir,
            {"ingest": INGEST_RESPONSE},
            exit_code=1,
        )

        result = run_tmt(
            self.repo, "note", "changed-files", "--json", env=self.env
        )

        payload = self.assert_json_error(result, "aiq-unavailable", 3)
        self.assertIn("stub failure", payload["error"])


class CandidatesTest(AiqStubTestCase):
    def test_candidates_groups_and_counts_tmt_notes(self) -> None:
        messages = [
            _note_message("foo"),
            _note_message("foo", "seen it again"),
            _note_message("bar"),
            {"source": "codex", "content": "not a tmt event"},
            {"source": "tmt", "content": "not json at all"},
        ]
        write_aiq_stub(
            self.bin_dir,
            self.capture_dir,
            {"inbox": _inbox_response(messages)},
        )

        payload = self.assert_json_success(
            run_tmt(self.repo, "candidates", "--json", env=self.env)
        )

        self.assertEqual(
            payload["candidates"],
            [
                {"count": 2, "notes": ["seen it again"], "slug": "foo"},
                {"count": 1, "notes": [], "slug": "bar"},
            ],
        )
        argv = self.captured_argv()
        self.assertEqual(argv[:3], ["inbox", "list", "--json"])
        self.assertIn("--include-content", argv)

    def test_candidates_human_output(self) -> None:
        messages = [
            _note_message("foo"),
            _note_message("foo"),
            _note_message("bar"),
        ]
        write_aiq_stub(
            self.bin_dir,
            self.capture_dir,
            {"inbox": _inbox_response(messages)},
        )

        result = run_tmt(self.repo, "candidates", env=self.env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2\tfoo\n1\tbar\n")

    def test_candidates_when_aiq_is_absent(self) -> None:
        result = run_tmt(
            self.repo,
            "candidates",
            "--json",
            env={"PATH": os.fspath(self.bin_dir)},
        )

        self.assert_json_error(result, "aiq-unavailable", 3)


if __name__ == "__main__":
    unittest.main()

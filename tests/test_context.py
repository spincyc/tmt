"""`tmt context`: the SessionStart hook payload generator.

Fail-open is the hard requirement under test: every failure path must
exit 0 with clean stderr, printing the tool list when available and
nothing otherwise.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

from _support import (
    TmtTestCase,
    run_tmt,
    save_registry,
    write_aiq_stub,
)

TOOLS_HEADER = "tmt: repo tools (tools/<id> --help; see tmt.json)"
CANDIDATES_HEADER = "tmt: noted candidates (build at 2+ with tmt new)"


def _entry(purpose: str, stage: str = "draft") -> dict[str, Any]:
    return {"purpose": purpose, "stage": stage, "usage": "tools/x [--json]"}


def _note_message(slug: str) -> dict[str, str]:
    return {
        "source": "tmt",
        "content": json.dumps(
            {"kind": "tmt-note", "note": None, "slug": slug},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _inbox_response(messages: list[dict[str, str]]) -> str:
    return json.dumps({"messages": messages, "v": 1}) + "\n"


class ContextTestCase(TmtTestCase):
    def setUp(self) -> None:
        self.bin_dir = self.make_dir()
        self.capture_dir = self.make_dir()
        self.no_aiq_env = {"PATH": os.fspath(self.bin_dir)}
        self.stub_env = {
            "PATH": f"{os.fspath(self.bin_dir)}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        }

    def run_context(
        self, root: Any, env: dict[str, str]
    ) -> Any:
        return run_tmt(root, "context", env=env, stdin_text="")

    def assert_silent_success(self, result: Any) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


class ContextTest(ContextTestCase):
    def test_no_registry_prints_nothing_and_exits_0(self) -> None:
        root = self.make_dir()

        self.assert_silent_success(self.run_context(root, self.no_aiq_env))

    def test_empty_registry_prints_nothing(self) -> None:
        root = self.make_repo()

        self.assert_silent_success(self.run_context(root, self.no_aiq_env))

    def test_tool_list_output(self) -> None:
        root = self.make_repo()
        save_registry(
            root,
            {
                "tools": {
                    "beta": _entry("Second purpose"),
                    "alpha": _entry("First purpose", stage="stable"),
                },
                "v": 1,
            },
        )

        result = self.run_context(root, self.no_aiq_env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            f"{TOOLS_HEADER}\n"
            "  alpha (stable): First purpose\n"
            "  beta (draft): Second purpose\n",
        )

    def test_candidates_section_with_stub_aiq(self) -> None:
        root = self.make_repo()
        save_registry(
            root, {"tools": {"alpha": _entry("First purpose")}, "v": 1}
        )
        write_aiq_stub(
            self.bin_dir,
            self.capture_dir,
            {
                "inbox": _inbox_response(
                    [
                        _note_message("foo"),
                        _note_message("foo"),
                        _note_message("bar"),
                    ]
                )
            },
        )

        result = self.run_context(root, self.stub_env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"{TOOLS_HEADER}\n"
            "  alpha (draft): First purpose\n"
            f"{CANDIDATES_HEADER}\n"
            "  foo x2\n"
            "  bar x1\n",
        )

    def test_broken_aiq_fails_open_to_the_tool_list(self) -> None:
        root = self.make_repo()
        save_registry(
            root, {"tools": {"alpha": _entry("First purpose")}, "v": 1}
        )
        write_aiq_stub(
            self.bin_dir, self.capture_dir, {}, exit_code=1
        )

        result = self.run_context(root, self.stub_env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            f"{TOOLS_HEADER}\n  alpha (draft): First purpose\n",
        )

    def test_invalid_registry_fails_open_to_silence(self) -> None:
        root = self.make_repo()
        (root / "tmt.json").write_text("{not json\n", encoding="utf-8")

        self.assert_silent_success(self.run_context(root, self.no_aiq_env))

    def test_output_is_capped_at_40_lines_with_elision(self) -> None:
        root = self.make_repo()
        tools = {
            f"tool-{index:02d}": _entry(f"Purpose {index}")
            for index in range(45)
        }
        save_registry(root, {"tools": tools, "v": 1})

        result = self.run_context(root, self.no_aiq_env)

        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 40)
        self.assertEqual(lines[0], TOOLS_HEADER)
        # 1 header + 45 tools = 46 total; 39 kept + 1 elision line.
        self.assertEqual(lines[-1], "  ... (7 more; read tmt.json)")

    def test_hook_style_stdin_is_consumed_and_ignored(self) -> None:
        root = self.make_repo()
        save_registry(
            root, {"tools": {"alpha": _entry("First purpose")}, "v": 1}
        )

        result = run_tmt(
            root,
            "context",
            env=self.no_aiq_env,
            stdin_text='{"session_id": "abc", "source": "startup"}\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("alpha (draft)", result.stdout)


if __name__ == "__main__":
    unittest.main()

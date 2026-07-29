"""Shared helpers for the tmt test suite.

Every test drives the CLI as a subprocess: ``[sys.executable, "-m", "tmt"]``
with PYTHONPATH pointing at ``src/``, asserting on exact JSON fields, exit
codes, and stderr error codes (aiq cli-v1 protocol).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

AIQ_STUB_TEMPLATE = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

CAPTURE = Path({capture!r})
RESPONSES = {responses!r}
EXIT_CODE = {exit_code!r}

with CAPTURE.joinpath("argv.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
command = sys.argv[1] if len(sys.argv) > 1 else ""
if command == "ingest":
    CAPTURE.joinpath("stdin.txt").write_text(
        sys.stdin.read(), encoding="utf-8"
    )
if EXIT_CODE != 0:
    print("stub failure", file=sys.stderr)
    sys.exit(EXIT_CODE)
sys.stdout.write(RESPONSES.get(command, "{{}}\\n"))
sys.exit(0)
"""


def run_tmt(
    cwd: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.fspath(SRC_DIR)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "tmt", *arguments],
        cwd=os.fspath(cwd),
        env=environment,
        text=True,
        input=stdin_text,
        capture_output=True,
    )


def run_git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(cwd), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def git_init_commit(repository: Path, message: str = "initial") -> str:
    """git init + commit everything present; return the HEAD commit hash."""
    run_git(repository, "init", "-q", "-b", "main")
    run_git(repository, "add", "-A")
    run_git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-q",
        "--no-gpg-sign",
        "-m",
        message,
    )
    return run_git(repository, "rev-parse", "HEAD").strip()


def load_registry(root: Path) -> dict[str, Any]:
    return json.loads((root / "tmt.json").read_text(encoding="utf-8"))


def save_registry(root: Path, data: dict[str, Any]) -> None:
    (root / "tmt.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def write_aiq_stub(
    bin_dir: Path,
    capture_dir: Path,
    responses: dict[str, str],
    *,
    exit_code: int = 0,
) -> Path:
    """Place a fake ``aiq`` executable in ``bin_dir`` that records its
    argv (and stdin for ingest) into ``capture_dir`` and prints canned
    responses keyed by subcommand."""
    stub = bin_dir / "aiq"
    write_executable(
        stub,
        AIQ_STUB_TEMPLATE.format(
            capture=os.fspath(capture_dir),
            responses=responses,
            exit_code=exit_code,
        ),
    )
    return stub


class TmtTestCase(unittest.TestCase):
    """Base class: temp repos plus cli-v1 protocol assertions."""

    def make_dir(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()

    def make_repo(self) -> Path:
        root = self.make_dir()
        result = run_tmt(root, "init")
        self.assertEqual(result.returncode, 0, result.stderr)
        return root

    def parse_single_json(self, text: str) -> dict[str, Any]:
        """Assert ``text`` is exactly one compact key-sorted JSON object
        plus newline, with top-level ``"v": 1``; return the object."""
        self.assertTrue(text.endswith("\n"), f"missing newline: {text!r}")
        lines = text.splitlines()
        self.assertEqual(len(lines), 1, f"expected one line: {text!r}")
        payload = json.loads(lines[0])
        self.assertIsInstance(payload, dict)
        self.assertEqual(
            lines[0],
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "output is not compact key-sorted JSON",
        )
        self.assertEqual(payload["v"], 1)
        return payload

    def assert_json_success(
        self, result: subprocess.CompletedProcess[str]
    ) -> dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return self.parse_single_json(result.stdout)

    def assert_json_error(
        self,
        result: subprocess.CompletedProcess[str],
        code: str,
        exit_code: int,
    ) -> dict[str, Any]:
        self.assertEqual(result.returncode, exit_code, result.stderr)
        self.assertEqual(result.stdout, "", "error output must not hit stdout")
        payload = self.parse_single_json(result.stderr)
        self.assertEqual(
            sorted(payload), ["code", "error", "status", "v"]
        )
        self.assertEqual(payload["code"], code)
        self.assertEqual(payload["status"], "error")
        return payload

    def check_json(
        self, root: Path
    ) -> tuple[int, list[str], list[str]]:
        result = run_tmt(root, "check", "--json")
        payload = self.parse_single_json(result.stdout)
        return result.returncode, payload["failures"], payload["warnings"]

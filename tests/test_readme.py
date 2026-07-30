"""The README quickstart is executable, and it is executed here.

DESIGN.md claims a doc-tested README; this is that test. The quickstart's
first shell block under the Quickstart heading runs verbatim in a scratch
directory against the working tree, so prose that stops matching the CLI
is a build failure rather than a discovery.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from _support import SRC_DIR, TmtTestCase

README = Path(__file__).resolve().parent.parent / "README.md"
_HEADING_RE = re.compile(r"^##\s+Quickstart\s*$", re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)
_BLOCK_RE = re.compile(r"^```sh\n(?P<body>.*?)^```$", re.DOTALL | re.MULTILINE)

TMT_SHIM = """#!/bin/sh
exec {python} -m tmt "$@"
"""


def quickstart_block() -> str:
    """The Quickstart section's first ```sh block.

    The search stops at the next `## ` heading, so a block belonging to a
    later section can never stand in for a Quickstart that lost its own.
    """
    text = README.read_text(encoding="utf-8")
    heading = _HEADING_RE.search(text)
    if heading is None:
        raise AssertionError("README.md has no '## Quickstart' heading")
    following = _NEXT_HEADING_RE.search(text, heading.end())
    section = text[heading.end() : following.start() if following else None]
    block = _BLOCK_RE.search(section)
    if block is None:
        raise AssertionError("README.md Quickstart has no ```sh block")
    return block.group("body")


class ReadmeQuickstartTest(TmtTestCase):
    def test_quickstart_block_runs_verbatim(self) -> None:
        script = quickstart_block()
        self.assertIn("tmt init", script, "quickstart no longer inits")
        workspace = self.make_dir()
        shim_dir = self.make_dir()
        shim = shim_dir / "tmt"
        shim.write_text(
            TMT_SHIM.format(python=sys.executable), encoding="utf-8"
        )
        shim.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = (
            f"{os.fspath(shim_dir)}{os.pathsep}{environment.get('PATH', '')}"
        )
        environment["PYTHONPATH"] = os.fspath(SRC_DIR)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        # The block runs `mktemp -d`, so without this the directory it
        # creates outlives the test and accumulates on every run.
        environment["TMPDIR"] = os.fspath(workspace)
        # The block is documentation, not a test harness: -e makes any
        # silent failure inside it fail here.
        completed = subprocess.run(
            ["sh", "-e", "-c", script],
            cwd=os.fspath(workspace),
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"README quickstart failed\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()

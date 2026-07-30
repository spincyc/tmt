"""Mirror candidate notes to aiq through its CLI only.

tmt never reads aiq's SQLite journal and never imports aiq modules; the
journal schema is declared internal. Candidate events use the canonical
provider-neutral v1 envelope from aiq docs/integrations/generic.md, with
``source: "tmt"`` plus a ``"kind": "tmt-note"`` content marker so a
reader can filter them back out of ``aiq inbox list --json``. Counting
lives in ``tmt.notestore``: the loop must not require aiq.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tmt.registry import TmtError

SOURCE = "tmt"
NOTE_KIND = "tmt-note"
_TIMEOUT_SECONDS = 5


def _run(
    arguments: list[str], *, cwd: Path, stdin_text: str | None = None
) -> str:
    executable = shutil.which("aiq")
    if executable is None:
        raise TmtError("aiq-unavailable", "aiq executable not found on PATH")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            cwd=cwd,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise TmtError(
            "aiq-unavailable",
            f"aiq did not finish within {_TIMEOUT_SECONDS}s",
        ) from None
    except OSError as error:
        raise TmtError(
            "aiq-unavailable", f"aiq could not run: {error}"
        ) from error
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip().splitlines()
            or [f"exit {completed.returncode}"]
        )[0]
        raise TmtError(
            "aiq-unavailable", f"aiq {arguments[0]} failed: {detail}"
        )
    return completed.stdout


def _parse(stdout: str, *, command: str) -> dict[str, Any]:
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise TmtError(
            "aiq-unavailable",
            f"aiq {command} returned unparseable JSON: {error}",
        ) from error
    if not isinstance(result, dict):
        raise TmtError(
            "aiq-unavailable", f"aiq {command} returned a non-object result"
        )
    return result


def note(slug: str, note_text: str | None, *, cwd: Path) -> dict[str, Any]:
    """Emit one tool-candidate event via ``aiq ingest --event-json -``."""
    content = json.dumps(
        {"kind": NOTE_KIND, "note": note_text, "slug": slug},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    event = {
        "v": 1,
        "source": SOURCE,
        "content": content,
        "cwd": os.fspath(cwd.resolve()),
    }
    stdout = _run(
        ["ingest", "--event-json", "-", "--json"],
        cwd=cwd,
        stdin_text=json.dumps(
            event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n",
    )
    result = _parse(stdout, command="ingest")
    return {
        "created": result.get("created"),
        "message_id": result.get("message_id"),
    }

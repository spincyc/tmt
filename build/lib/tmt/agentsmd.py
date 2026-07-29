"""The canonical AGENTS.md habit fragment and its marker-block lifecycle.

Layer 1 of the note habit: one versioned fragment (a contract — verify
caps it at 50 words). Layer 2: the fragment lives in a repo's AGENTS.md
between owned marker lines, written idempotently by ``tmt agents
--write`` and byte-checked by the ``tmt check`` gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tmt.registry import TmtError

FRAGMENT_VERSION = 1
FRAGMENT = (
    "Before writing any script, read tmt.json and prefer a listed tool\n"
    "(`tools/<id> --help`). After deriving anything repeatable, run\n"
    "`tmt note <slug>`; at two notes build it with `tmt new <slug>`.\n"
    "Keep the registry honest with `tmt check`."
)
FRAGMENT_MAX_WORDS = 50

AGENTS_FILENAME = "AGENTS.md"
BEGIN_MARKER = f"<!-- tmt:agents v{FRAGMENT_VERSION} -->"
END_MARKER = "<!-- /tmt:agents -->"
_BEGIN_PREFIX = "<!-- tmt:agents"

STALE_FAILURE = "AGENTS.md tmt fragment is stale; run `tmt agents --write`"
MALFORMED_FAILURE = (
    "AGENTS.md tmt block is malformed: begin marker without end marker"
)


def render_block() -> str:
    """The exact owned block, begin marker through end marker, no newline."""
    return f"{BEGIN_MARKER}\n{FRAGMENT}\n{END_MARKER}"


def _locate(lines: list[str]) -> tuple[int, int | None] | None:
    """(begin, end) line indexes of the marker block; end ``None`` when the
    begin marker has no matching end marker; ``None`` when absent."""
    for index, line in enumerate(lines):
        if line.startswith(_BEGIN_PREFIX):
            for later in range(index + 1, len(lines)):
                if lines[later] == END_MARKER:
                    return index, later
            return index, None
    return None


def status(root: Path) -> dict[str, Any]:
    """Fragment status in ``root``/AGENTS.md:
    installed | stale | absent | no-agents-file."""
    path = root / AGENTS_FILENAME
    result: dict[str, Any] = {
        "fragment_version": FRAGMENT_VERSION,
        "path": str(path),
    }
    if not path.is_file():
        result["status"] = "no-agents-file"
        return result
    lines = path.read_text(encoding="utf-8").split("\n")
    location = _locate(lines)
    if location is None:
        result["status"] = "absent"
        return result
    begin, end = location
    if end is None:
        result["status"] = "stale"  # malformed: needs manual repair
        return result
    block = "\n".join(lines[begin : end + 1])
    result["status"] = "installed" if block == render_block() else "stale"
    return result


def write(root: Path) -> dict[str, Any]:
    """Create AGENTS.md or idempotently insert/replace the marker block."""
    path = root / AGENTS_FILENAME
    block = render_block()
    result: dict[str, Any] = {
        "fragment_version": FRAGMENT_VERSION,
        "path": str(path),
        "status": "installed",
    }
    if not path.is_file():
        path.write_text(block + "\n", encoding="utf-8")
        return {**result, "changed": True, "previous": "no-agents-file"}
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    location = _locate(lines)
    if location is None:
        if text == "":
            updated = block + "\n"
        else:
            body = text if text.endswith("\n") else text + "\n"
            updated = f"{body}\n{block}\n"
        path.write_text(updated, encoding="utf-8")
        return {**result, "changed": True, "previous": "absent"}
    begin, end = location
    if end is None:
        raise TmtError(
            "check-failed",
            f"{path}: tmt begin marker has no matching end marker "
            f"({END_MARKER}); repair the block by hand",
        )
    if "\n".join(lines[begin : end + 1]) == block:
        return {**result, "changed": False, "previous": "installed"}
    lines[begin : end + 1] = block.split("\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return {**result, "changed": True, "previous": "stale"}


def check_failures(root: Path) -> list[str]:
    """The ``tmt check`` gate: a present marker block must be current.

    A missing AGENTS.md or one without markers is never a failure —
    repos may decline the fragment. A malformed or stale block fails.
    """
    path = root / AGENTS_FILENAME
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except UnicodeDecodeError:
        return []
    location = _locate(lines)
    if location is None:
        return []
    begin, end = location
    if end is None:
        return [MALFORMED_FAILURE]
    if "\n".join(lines[begin : end + 1]) != render_block():
        return [STALE_FAILURE]
    return []

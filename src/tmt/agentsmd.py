"""The canonical AGENTS.md habit fragment and its marker-block lifecycle.

Layer 1 of the note habit: one versioned fragment (a contract — verify
caps it at 50 words). Layer 2: the fragment lives in a repo's AGENTS.md
between owned marker lines, written idempotently by ``tmt agents
--write`` and byte-checked by the ``tmt check`` gate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tmt import paths
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
# Only a versioned begin marker owns a block: prose such as
# `<!-- tmt:agents-example -->` must never claim the content below it.
_BEGIN_RE = re.compile(r"<!-- tmt:agents v(\d+) -->")

STALE_FAILURE = "AGENTS.md tmt fragment is stale; run `tmt agents --write`"
MALFORMED_FAILURE = (
    "AGENTS.md tmt block is malformed: begin marker without end marker"
)
DUPLICATE_FAILURE = (
    "AGENTS.md has more than one tmt block; keep exactly one and delete "
    "the rest"
)


def render_block() -> str:
    """The exact owned block, begin marker through end marker, no newline."""
    return f"{BEGIN_MARKER}\n{FRAGMENT}\n{END_MARKER}"


def _begins(lines: list[str]) -> list[int]:
    return [
        index
        for index, line in enumerate(lines)
        if _BEGIN_RE.fullmatch(line.strip())
    ]


def _locate(lines: list[str]) -> tuple[int, int | None] | None:
    """(begin, end) line indexes of the marker block; end ``None`` when the
    begin marker has no matching end marker; ``None`` when absent."""
    begins = _begins(lines)
    if not begins:
        return None
    index = begins[0]
    for later in range(index + 1, len(lines)):
        if lines[later].strip() == END_MARKER:
            return index, later
    return index, None


def _read_text(path: Path) -> str:
    """The file's exact bytes decoded, line terminators untranslated."""
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as error:
        raise TmtError(
            "check-failed", f"{path} is not valid UTF-8: {error}"
        ) from error
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error


def _read_lines(path: Path) -> tuple[list[str], str]:
    """Physical lines without terminators, plus the file's line ending."""
    text = _read_text(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    return [line.removesuffix("\r") for line in text.split("\n")], newline


def _splice(text: str, block: str) -> str | None:
    """``text`` with the owned block replaced, everything else byte-exact.

    Only the block's own lines are rewritten, and each keeps the
    terminator it already had, so a CRLF or mixed-ending file survives.
    ``None`` when no begin marker is present.
    """
    physical = text.splitlines(keepends=True)
    begin = next(
        (
            index
            for index, line in enumerate(physical)
            if _BEGIN_RE.fullmatch(line.strip())
        ),
        None,
    )
    if begin is None:
        return None
    end = next(
        (
            index
            for index in range(begin + 1, len(physical))
            if physical[index].strip() == END_MARKER
        ),
        None,
    )
    if end is None:
        return None
    newline = "\r\n" if physical[begin].endswith("\r\n") else "\n"
    terminator = ""
    for suffix in ("\r\n", "\n"):
        if physical[end].endswith(suffix):
            terminator = suffix
            break
    rendered = newline.join(block.split("\n")) + terminator
    return "".join([*physical[:begin], rendered, *physical[end + 1:]])


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
    lines, _ = _read_lines(path)
    if len(_begins(lines)) > 1:
        result["status"] = "stale"  # duplicate blocks need manual repair
        return result
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
    paths.resolve_within(root, path, label=AGENTS_FILENAME)
    block = render_block()
    result: dict[str, Any] = {
        "fragment_version": FRAGMENT_VERSION,
        "path": str(path),
        "status": "installed",
    }
    if not path.is_file():
        paths.write_atomic(path, block + "\n")
        return {**result, "changed": True, "previous": "no-agents-file"}
    lines, newline = _read_lines(path)
    if len(_begins(lines)) > 1:
        raise TmtError(
            "check-failed",
            f"{path}: {DUPLICATE_FAILURE}",
        )
    location = _locate(lines)
    if location is None:
        if lines == [""]:
            updated = [*block.split("\n"), ""]
        else:
            body = lines if lines[-1] == "" else [*lines, ""]
            updated = [*body, *block.split("\n"), ""]
        paths.write_atomic(path, newline.join(updated))
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
    spliced = _splice(_read_text(path), block)
    if spliced is None:
        raise TmtError(
            "check-failed",
            f"{path}: tmt block could not be located for replacement; "
            "repair the block by hand",
        )
    paths.write_atomic(path, spliced)
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
        lines, _ = _read_lines(path)
    except TmtError:
        return []
    if len(_begins(lines)) > 1:
        return [DUPLICATE_FAILURE]
    location = _locate(lines)
    if location is None:
        return []
    begin, end = location
    if end is None:
        return [MALFORMED_FAILURE]
    if "\n".join(lines[begin : end + 1]) != render_block():
        return [STALE_FAILURE]
    return []

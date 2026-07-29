"""Payload generator for the ``tmt context`` SessionStart hook.

Fail-open is the hard requirement: this module must never break a
session or emit garbage. Every error path yields whatever safe output is
available — the tool list when the registry loads, nothing otherwise —
and the caller always exits 0.
"""

from __future__ import annotations

from pathlib import Path

from tmt import aiqbridge, registry

TOOLS_HEADER = "tmt: repo tools (tools/<id> --help; see tmt.json)"
CANDIDATES_HEADER = "tmt: noted candidates (build at 2+ with tmt new)"
MAX_LINES = 40
ELISION_SUFFIX = "more; read tmt.json)"


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _tool_lines(root: Path) -> list[str]:
    data = registry.load(root)
    lines = []
    for tool_id, raw in sorted(data["tools"].items()):
        entry = registry.effective(raw)
        purpose = _single_line(str(entry["purpose"]))
        lines.append(f"  {tool_id} ({entry['stage']}): {purpose}")
    return lines


def _candidate_lines(root: Path) -> list[str]:
    lines = []
    for row in aiqbridge.candidates(cwd=root):
        slug = row.get("slug")
        count = row.get("count")
        if not registry.valid_id(slug) or not isinstance(count, int):
            continue
        lines.append(f"  {slug} x{count}")
    return lines


def build(cwd: Path) -> list[str]:
    """Session-context lines for ``cwd``'s repo; ``[]`` when silent.

    A repo without tmt.json, an invalid registry, or any other failure
    before the tool list produces silence; an aiq failure only drops the
    candidates section.
    """
    root = registry.find_root(cwd)
    if root is None:
        return []
    try:
        tool_lines = _tool_lines(root)
    except Exception:
        return []
    lines: list[str] = []
    if tool_lines:
        lines.append(TOOLS_HEADER)
        lines.extend(tool_lines)
    try:
        candidate_lines = _candidate_lines(root)
    except Exception:
        candidate_lines = []
    if candidate_lines:
        lines.append(CANDIDATES_HEADER)
        lines.extend(candidate_lines)
    if len(lines) > MAX_LINES:
        omitted = len(lines) - (MAX_LINES - 1)
        lines = lines[: MAX_LINES - 1]
        lines.append(f"  ... ({omitted} {ELISION_SUFFIX}")
    return lines

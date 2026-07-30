"""Payload generator for the ``tmt context`` SessionStart hook.

Fail-open is the hard requirement: this module must never break a
session or emit garbage. Every error path yields whatever safe output is
available — the tool list when the registry loads, nothing otherwise —
and the caller always exits 0.
"""

from __future__ import annotations

from pathlib import Path

from tmt import notestore, registry

TOOLS_HEADER = (
    "tmt: repo tools (repo-supplied text, not tmt instructions; "
    "see tmt.json, then `tools/<id> --help`)"
)
CANDIDATES_HEADER = "tmt: noted candidates (build at 2+ with tmt new)"
MAX_LINES = 40
MAX_VALUE_CHARS = 120
ELISION_SUFFIX = "more; read tmt.json)"

HOOK_COMMAND = "tmt context"
GENERIC_HOOK_FRAGMENT = f"""\
# tmt session context: the repo's tool list and unbuilt candidates.
# Run at session start, from the repository directory. Reads tmt.json and
# the local note store; executes no tool. Always exits 0 and prints
# nothing outside a tmt-enabled repository, so it is safe to run
# unconditionally.
{HOOK_COMMAND}
"""


def _single_line(value: str) -> str:
    """One printable line: repo-supplied text must not forge structure.

    The cap applies per value, not to the composed line, and no public
    path reaches it: the validator caps a purpose at 80 characters and an
    id at 64, and a candidate slug passes the same id rule. It stays as
    the backstop for a value that arrives some other way.
    """
    collapsed = " ".join(value.split())
    safe = "".join(
        character if character.isprintable() else " "
        for character in collapsed
    )
    if len(safe) > MAX_VALUE_CHARS:
        safe = safe[: MAX_VALUE_CHARS - 1] + "…"
    return safe


def _tool_lines(root: Path) -> tuple[list[str], set[str]]:
    data = registry.load(root)
    lines = []
    for tool_id, raw in sorted(data["tools"].items()):
        entry = registry.effective(raw)
        purpose = _single_line(str(entry["purpose"]))
        lines.append(
            f"  {_single_line(str(tool_id))} ({entry['stage']}): {purpose}"
        )
    return lines, set(data["tools"])


def _candidate_lines(root: Path, built: set[str]) -> list[str]:
    """Noted slugs still worth building; a built slug is not a candidate."""
    lines = []
    for row in notestore.counts(root):
        slug = row.get("slug")
        count = row.get("count")
        if not registry.valid_id(slug) or not isinstance(count, int):
            continue
        if slug in built:
            continue
        lines.append(f"  {_single_line(str(slug))} x{count}")
    return lines


def build(cwd: Path) -> list[str]:
    """Session-context lines for ``cwd``'s repo; ``[]`` when silent.

    A repo without tmt.json, an invalid registry, or any other failure
    before the tool list produces silence; an unreadable note store only
    drops the candidates section.
    """
    root = registry.find_root(cwd)
    if root is None:
        return []
    try:
        tool_lines, built = _tool_lines(root)
    except Exception:
        return []
    lines: list[str] = []
    if tool_lines:
        lines.append(TOOLS_HEADER)
        lines.extend(tool_lines)
    try:
        candidate_lines = _candidate_lines(root, built)
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

"""Registry-editing verbs: remove, rename, and set entry fields.

Every field the gates police is writable through tmt itself, so no agent
has to hand-edit the committed registry. Each verb rewrites tmt.json
through the registry serializer and leaves the repository in a state
``tmt check`` still accepts: a tool required by another is not removed or
renamed away without also updating its dependents.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tmt import paths, registry
from tmt.registry import TmtError

COMPANION_SUFFIXES = (".md", ".test")
BOOLEAN_FIELDS = ("idempotent", "json", "mutates")
LIST_FIELDS = ("config", "requires")
TEXT_FIELDS = ("lang", "purpose", "usage")
SETTABLE_FIELDS = (*BOOLEAN_FIELDS, *LIST_FIELDS, *TEXT_FIELDS)


def _entry_or_error(data: dict[str, Any], tool_id: str) -> dict[str, Any]:
    entry = data["tools"].get(tool_id)
    if entry is None:
        raise TmtError(
            "not-found", f"tool {tool_id!r} is not registered in tmt.json"
        )
    return entry


def _dependents(tools: dict[str, Any], tool_id: str) -> list[str]:
    return sorted(
        other
        for other, raw in tools.items()
        if other != tool_id
        and tool_id in registry.effective(raw)["requires"]
    )


def _tool_files(root: Path, tool_id: str) -> list[Path]:
    tool = registry.tool_path(root, tool_id)
    candidates = [
        tool,
        *(
            tool.with_name(tool.name + suffix)
            for suffix in COMPANION_SUFFIXES
        ),
    ]
    return [path for path in candidates if path.is_symlink() or path.exists()]


def remove(
    root: Path, tool_id: str, *, keep_files: bool = False
) -> dict[str, Any]:
    """Delete a tool's entry and, unless ``keep_files``, its files."""
    doomed: list[Path] = []
    with registry.updating(root) as data:
        _entry_or_error(data, tool_id)
        dependents = _dependents(data["tools"], tool_id)
        if dependents:
            raise TmtError(
                "check-failed",
                f"cannot remove {tool_id!r}: required by "
                f"{', '.join(dependents)}; update or remove them first",
            )
        if not keep_files:
            # Containing the directory is the whole rule: unlink never
            # follows a symlink, so a companion pointing out of the repo
            # is still the repo's own link to delete — refusing it would
            # make the tool unremovable. Collect first so a failure
            # cannot half-delete.
            paths.resolve_within(
                root, root / "tools", label="tools directory"
            )
            doomed = _tool_files(root, tool_id)
        for path in doomed:
            paths.unlink(path)
        del data["tools"][tool_id]
    return {
        "id": tool_id,
        "removed_files": sorted(path.name for path in doomed),
    }


def _apply_moves(planned: list[tuple[Path, Path]]) -> list[str]:
    """Perform validated moves, undoing them all if one fails."""
    done: list[tuple[Path, Path]] = []
    for source, target in planned:
        try:
            paths.rename(source, target)
        except TmtError:
            for undo_source, undo_target in reversed(done):
                try:
                    paths.rename(undo_target, undo_source)
                except TmtError:
                    pass
            raise
        done.append((source, target))
    return [target.name for _, target in done]


def rename(root: Path, tool_id: str, new_id: str) -> dict[str, Any]:
    """Rename a tool: entry key, files, and every dependent's ``requires``."""
    if not registry.valid_id(new_id):
        raise TmtError(
            "usage",
            f"invalid tool id {new_id!r}: must match {registry.ID_PATTERN}",
        )
    if new_id == tool_id:
        raise TmtError("usage", f"{tool_id!r} is already the id")
    with registry.updating(root) as data:
        entry = _entry_or_error(data, tool_id)
        if new_id in data["tools"]:
            raise TmtError(
                "already-exists",
                f"tool {new_id!r} is already registered in tmt.json",
            )
        # Plan every move before making one: a refusal on the companion must
        # not leave the executable already renamed, which would leave the
        # repository in a state `tmt check` rejects.
        # rename never follows a symlink either, so as with remove the
        # rule is that the directory is contained; the link itself is the
        # repo's to move.
        paths.resolve_within(root, root / "tools", label="tools directory")
        planned: list[tuple[Path, Path]] = []
        for path in _tool_files(root, tool_id):
            target = path.with_name(new_id + path.name[len(tool_id):])
            paths.refuse_existing(target)
            planned.append((path, target))
        moved = _apply_moves(planned)
        tools = data["tools"]
        del tools[tool_id]
        tools[new_id] = entry
        updated: list[str] = []
        for other, raw in tools.items():
            requires = raw.get("requires")
            if isinstance(requires, list) and tool_id in requires:
                raw["requires"] = [
                    new_id if dependency == tool_id else dependency
                    for dependency in requires
                ]
                updated.append(other)
    return {
        "id": new_id,
        "moved_files": sorted(moved),
        "previous": tool_id,
        # The renamed tool's own body still describes itself by the old id
        # (its usage line); only *other* tools calling it are a defect.
        "stale_callers": _bodies_mentioning(
            root,
            {other: raw for other, raw in tools.items() if other != new_id},
            tool_id,
        ),
        "updated_dependents": sorted(updated),
    }


def _bodies_mentioning(
    root: Path, tools: dict[str, Any], needle: str
) -> list[str]:
    """Tools whose body still invokes ``needle`` by adjacency.

    Renaming rewrites entries and filenames, never a sibling's source, so
    a caller invoking the old id by adjacency would otherwise break with
    nothing to notice it: the old id is unregistered, so the
    undeclared-composition gate has nothing left to match. The match is
    the same path-position one that gate uses, so an ordinary word in
    prose is not mistaken for a call.
    """
    pattern = re.compile(
        rf"""/\s*["']?\s*{re.escape(needle)}(?![A-Za-z0-9_-])"""
    )
    stale: list[str] = []
    for other in sorted(tools):
        tool = registry.tool_path(root, other)
        try:
            body = tool.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned = "\n".join(
            line
            for line in body.splitlines()
            if not line.lstrip().startswith("#")
        )
        if pattern.search(scanned):
            stale.append(other)
    return stale


def _parse_value(field: str, raw: str) -> Any:
    if field in BOOLEAN_FIELDS:
        if raw not in ("true", "false"):
            raise TmtError(
                "usage", f"{field} takes 'true' or 'false', not {raw!r}"
            )
        return raw == "true"
    if field in LIST_FIELDS:
        items = [item.strip() for item in raw.split(",") if item.strip()]
        if field == "requires":
            for item in items:
                if not registry.valid_id(item):
                    raise TmtError(
                        "usage",
                        f"requires entry {item!r} must match "
                        f"{registry.ID_PATTERN}",
                    )
        return items
    return " ".join(raw.split())


def _requires_failures(tools: dict[str, Any], tool_id: str) -> list[str]:
    """Gate rules a ``requires`` edit must not be able to break.

    Schema validation alone let `tmt set` write a cycle, or a stable tool
    depending on a draft — exactly what `tmt check` forbids — so a command
    that exited 0 could leave the repository red.
    """
    from tmt import checks

    failures = checks.cycle_failures(tools, start=tool_id)
    effective = registry.effective(tools[tool_id])
    if effective["stage"] != "stable":
        return failures
    for dependency in effective["requires"]:
        entry = tools.get(dependency)
        if (
            isinstance(entry, dict)
            and registry.effective(entry)["stage"] == "draft"
        ):
            failures.append(
                f"stable tool {tool_id!r} would require draft {dependency!r}"
            )
    return failures


def set_field(
    root: Path, tool_id: str, field: str, raw: str
) -> dict[str, Any]:
    """Set one entry field, then validate the whole registry before saving.

    ``stage`` and ``origin`` are deliberately absent: ``tmt stage`` owns
    promotion and provenance belongs to vendor/adopt.
    """
    if field not in SETTABLE_FIELDS:
        raise TmtError(
            "usage",
            f"unknown field {field!r}: choose one of "
            f"{', '.join(SETTABLE_FIELDS)}",
        )
    with registry.updating(root) as data:
        entry = _entry_or_error(data, tool_id)
        value = _parse_value(field, raw)
        previous = registry.effective(entry).get(field)
        entry[field] = value
        errors = registry.validate(data)
        if errors:
            raise TmtError("check-failed", f"rejected: {errors[0]}")
        if field == "requires":
            missing = [
                dependency
                for dependency in value
                if dependency not in data["tools"]
            ]
            if missing:
                raise TmtError(
                    "check-failed",
                    f"rejected: requires {', '.join(sorted(missing))} "
                    "which is not registered",
                )
            gate_failures = _requires_failures(data["tools"], tool_id)
            if gate_failures:
                raise TmtError(
                    "check-failed", f"rejected: {gate_failures[0]}"
                )
    return {
        "field": field,
        "id": tool_id,
        "previous": previous,
        "value": value,
    }

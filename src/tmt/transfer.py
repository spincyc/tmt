"""Symmetric tool movement with provenance: vendor (in) and adopt (out).

Both directions copy the executable plus its tmt.json entry and stamp
``origin`` with the source repo path, commit, content sha256, and — when the
source has an ``origin`` remote — its ``url``. Vendoring and re-adoption are
deliberate overwrites; divergence afterwards is allowed. Declared ``config``
files are never copied (config is repo-specific by nature); when the entry
declares any, the result carries ``config`` so the CLI can remind the
consumer to create them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tmt import checks, paths, registry
from tmt.registry import TmtError

_COMPANION_SUFFIXES = (".md", ".test")
_GIT_TIMEOUT_SECONDS = 10


def _git_commit(repo: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_remote_url(repo: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(repo), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _origin_stamp(
    source_root: Path, copied_tool: Path, tool_id: str
) -> dict[str, str]:
    """Provenance for a copy out of ``source_root``.

    ``id`` records the source-side id because drift derives the source
    path from it: without it, renaming the local copy silently ends drift
    reporting, since the renamed id never existed upstream.
    """
    stamp = {
        "commit": _git_commit(source_root),
        "id": tool_id,
        "repo": os.fspath(source_root),
        "sha256": checks.sha256_file(copied_tool),
    }
    url = _git_remote_url(source_root)
    if url is not None:
        stamp["url"] = url
    return stamp


def _plan_destination(dest_root: Path, dest: Path, *, label: str) -> None:
    """Refuse a destination a copy would have to follow out of the repo.

    Copying writes through a symlinked destination, so containment has to
    cover the destination itself and not merely its directory. An existing
    regular file is left alone here: overwriting one is what re-vendoring
    means.
    """
    paths.resolve_within(dest_root, dest, label=label)
    if dest.is_symlink():
        raise TmtError(
            "containment",
            f"{label} {dest} is a symlink; tmt refuses to write through it",
        )


def _copy_tool(source_root: Path, dest_root: Path, tool_id: str) -> Path:
    """Copy a tool and its companions, or copy nothing at all.

    Every source and destination is contained-checked before the first byte
    is written, so a refusal cannot leave a half-copied tool behind for
    `tmt check` to find.
    """
    source = registry.tool_path(source_root, tool_id)
    dest = registry.tool_path(dest_root, tool_id)
    paths.resolve_within(source_root, source, label=f"source tools/{tool_id}")
    paths.resolve_within(dest_root, dest.parent, label="tools directory")
    _plan_destination(dest_root, dest, label=f"destination tools/{tool_id}")
    if source.resolve() == dest.resolve():
        raise TmtError(
            "usage",
            f"source and destination tools/{tool_id} are the same file",
        )
    planned: list[tuple[Path, Path]] = [(source, dest)]
    for suffix in _COMPANION_SUFFIXES:
        companion = source.with_name(source.name + suffix)
        if companion.is_file():
            paths.resolve_within(
                source_root,
                companion,
                label=f"source tools/{tool_id}{suffix}",
            )
            companion_dest = dest.with_name(dest.name + suffix)
            _plan_destination(
                dest_root,
                companion_dest,
                label=f"destination tools/{tool_id}{suffix}",
            )
            planned.append((companion, companion_dest))
    paths.make_directory(dest.parent)
    for source_path, dest_path in planned:
        _copy_file(source_path, dest_path)
    return dest


def _copy_file(source: Path, dest: Path) -> None:
    """Copy contents and mode without ever following a link at ``dest``.

    ``O_NOFOLLOW`` closes the window the planned containment check leaves
    open, and the mode is set through the descriptor so it cannot land on
    some other file either.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        mode = source.stat().st_mode & 0o777
        with source.open("rb") as reader:
            with os.fdopen(os.open(dest, flags, mode), "wb") as writer:
                shutil.copyfileobj(reader, writer)
                os.fchmod(writer.fileno(), mode)
    except OSError as error:
        raise TmtError("io-error", f"{dest}: {error}") from error


def _registered_tool(
    repo_root: Path, tool_id: str, *, role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (registry data, entry) for a tool that exists in ``repo_root``."""
    if not (repo_root / registry.REGISTRY_FILENAME).is_file():
        raise TmtError(
            "no-registry", f"{role} {repo_root} has no tmt.json"
        )
    data = registry.load(repo_root)
    entry = data["tools"].get(tool_id)
    if entry is None:
        raise TmtError(
            "not-found",
            f"tool {tool_id!r} is not registered in {role} {repo_root}",
        )
    tool = registry.tool_path(repo_root, tool_id)
    if not tool.is_file():
        raise TmtError("not-found", f"{tool} does not exist")
    return data, entry


def vendor(root: Path, source: Path, tool_id: str) -> dict[str, Any]:
    """Copy ``tool_id`` from ``source`` into the current repo, stamped."""
    source_root = source.resolve()
    _, entry = _registered_tool(source_root, tool_id, role="source repo")
    with registry.updating(root) as data:
        missing = [
            dependency
            for dependency in registry.effective(entry)["requires"]
            if dependency not in data["tools"]
        ]
        if missing:
            raise TmtError(
                "portability",
                f"tool {tool_id!r} requires "
                f"{', '.join(sorted(missing))} which is not registered "
                "here; vendor the dependencies first",
            )
        dest_tool = _copy_tool(source_root, root, tool_id)
        origin = _origin_stamp(source_root, dest_tool, tool_id)
        stamped = dict(entry)
        stamped["origin"] = origin
        data["tools"][tool_id] = stamped
    result: dict[str, Any] = {
        "id": tool_id,
        "origin": origin,
        "path": str(dest_tool.relative_to(root)),
    }
    config = registry.effective(entry)["config"]
    if config:
        result["config"] = config
    return result


def adopt(root: Path, tool_id: str, dest: Path) -> dict[str, Any]:
    """Portability-lint ``tool_id`` then copy it into ``dest``, stamped.

    Only stable tools may be adopted: hardening precedes trusting.
    """
    _, entry = _registered_tool(root, tool_id, role="repo")
    stage = registry.effective(entry)["stage"]
    if stage != "stable":
        raise TmtError(
            "portability",
            f"tool {tool_id!r} is {stage}; only stable tools can be "
            "adopted — hardening precedes trusting. Promote it first with "
            f"`tmt stage {tool_id} stable`",
        )
    dest_root = dest.resolve()
    if not (dest_root / registry.REGISTRY_FILENAME).is_file():
        raise TmtError(
            "no-registry",
            f"destination {dest_root} has no tmt.json; run tmt init there",
        )
    with registry.updating(dest_root) as dest_data:
        tool = registry.tool_path(root, tool_id)
        findings = checks.portability_findings(root, tool_id, tool)
        for dependency in registry.effective(entry)["requires"]:
            if dependency not in dest_data["tools"]:
                findings.append(
                    f"{tool_id}: requires {dependency!r} which is not "
                    "registered in the destination; adopt the "
                    "dependency first"
                )
        if findings:
            raise TmtError("portability", "; ".join(findings))
        dest_tool = _copy_tool(root, dest_root, tool_id)
        origin = _origin_stamp(root.resolve(), dest_tool, tool_id)
        stamped = dict(entry)
        stamped["origin"] = origin
        dest_data["tools"][tool_id] = stamped
    result: dict[str, Any] = {
        "id": tool_id,
        "origin": origin,
        "to": os.fspath(dest_root),
    }
    config = registry.effective(entry)["config"]
    if config:
        result["config"] = config
    return result

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

from tmt import checks, registry
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


def _origin_stamp(source_root: Path, copied_tool: Path) -> dict[str, str]:
    """Provenance for a copy out of ``source_root``: repo, commit, sha256,
    plus ``url`` when the source has an ``origin`` remote."""
    stamp = {
        "commit": _git_commit(source_root),
        "repo": os.fspath(source_root),
        "sha256": checks.sha256_file(copied_tool),
    }
    url = _git_remote_url(source_root)
    if url is not None:
        stamp["url"] = url
    return stamp


def _copy_tool(source_root: Path, dest_root: Path, tool_id: str) -> Path:
    source = registry.tool_path(source_root, tool_id)
    dest = registry.tool_path(dest_root, tool_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    shutil.copymode(source, dest)
    for suffix in _COMPANION_SUFFIXES:
        companion = source.with_name(source.name + suffix)
        if companion.is_file():
            target = dest.with_name(dest.name + suffix)
            shutil.copyfile(companion, target)
            shutil.copymode(companion, target)
    return dest


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
    data = registry.load(root)
    dest_tool = _copy_tool(source_root, root, tool_id)
    origin = _origin_stamp(source_root, dest_tool)
    stamped = dict(entry)
    stamped["origin"] = origin
    data["tools"][tool_id] = stamped
    registry.save(root, data)
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
    dest_data = registry.load(dest_root)
    tool = registry.tool_path(root, tool_id)
    findings = checks.portability_findings(root, tool_id, tool)
    for dependency in registry.effective(entry)["requires"]:
        if dependency not in dest_data["tools"]:
            findings.append(
                f"{tool_id}: requires {dependency!r} which is not registered "
                "in the destination; adopt the dependency first"
            )
    if findings:
        raise TmtError("portability", "; ".join(findings))
    dest_tool = _copy_tool(root, dest_root, tool_id)
    origin = _origin_stamp(root.resolve(), dest_tool)
    stamped = dict(entry)
    stamped["origin"] = origin
    dest_data["tools"][tool_id] = stamped
    registry.save(dest_root, dest_data)
    result: dict[str, Any] = {
        "id": tool_id,
        "origin": origin,
        "to": os.fspath(dest_root),
    }
    config = registry.effective(entry)["config"]
    if config:
        result["config"] = config
    return result

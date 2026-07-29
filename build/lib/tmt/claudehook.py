"""Reversible Claude Code SessionStart integration (aiq's pattern in
miniature).

tmt owns exactly one hook group in the user-level Claude Code
``settings.json``: a ``SessionStart`` entry running ``tmt context``. The
lifecycle is plan / install / check / uninstall with an ownership
manifest, a non-destructive surgical merge that preserves every
unrelated setting and hook group, and drift refusal: an owned entry
edited by anyone else is never silently replaced or removed.

The hook command uses the invoking console script's absolute path when
``sys.argv[0]`` names an executable ``tmt`` file; otherwise it falls
back to ``sys.executable -m tmt`` (the documented resolution order).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from tmt.registry import TmtError

MANIFEST_VERSION = 1
MATCHER = "startup|resume|clear"
HOOK_TIMEOUT_SECONDS = 10
SETTINGS_ENV = "TMT_CLAUDE_SETTINGS"
_HOOKS_KEY = "hooks"
_EVENT_KEY = "SessionStart"
_MANIFEST_REQUIRED = (
    "created_containers",
    "created_file",
    "entry",
    "integration",
    "scope",
    "settings",
    "v",
)


def settings_path() -> Path:
    """User-level settings.json; ``$TMT_CLAUDE_SETTINGS`` overrides."""
    override = os.environ.get(SETTINGS_ENV)
    if override:
        return Path(os.path.abspath(override))
    return Path.home() / ".claude" / "settings.json"


def manifest_path() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "tmt" / "integration" / "claude-user.json"


def tmt_command() -> str:
    """Quoted absolute command that reruns this tmt installation."""
    argv0 = sys.argv[0] if sys.argv else ""
    if Path(argv0).name == "tmt":
        absolute = Path(os.path.abspath(argv0))
        if absolute.is_file() and os.access(absolute, os.X_OK):
            return shlex.quote(os.fspath(absolute))
    return f"{shlex.quote(sys.executable)} -m tmt"


def hook_entry() -> dict[str, Any]:
    """The exact owned SessionStart hook group install would add."""
    return {
        "matcher": MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": f"{tmt_command()} context",
                "timeout": HOOK_TIMEOUT_SECONDS,
            }
        ],
    }


def settings_fragment() -> dict[str, Any]:
    """The settings.json fragment for externally managed configuration."""
    return {_HOOKS_KEY: {_EVENT_KEY: [hook_entry()]}}


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _equal(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def _load_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TmtError(
            "check-failed", f"{path} does not parse: {error}"
        ) from error
    if not isinstance(data, dict):
        raise TmtError("check-failed", f"{path} is not a JSON object")
    return data


def _groups(path: Path, document: dict[str, Any]) -> list[Any]:
    hooks = document.get(_HOOKS_KEY)
    if hooks is None:
        return []
    if not isinstance(hooks, dict):
        raise TmtError("check-failed", f"{path}: 'hooks' is not an object")
    groups = hooks.get(_EVENT_KEY)
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise TmtError(
            "check-failed", f"{path}: hooks.{_EVENT_KEY} is not an array"
        )
    return groups


def _write_settings(path: Path, document: dict[str, Any]) -> None:
    """Re-serialize preserving key order; the only permitted byte change."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmt-tmp")
    staging.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(staging, path)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    invalid = TmtError(
        "check-failed",
        f"integration manifest {path} is invalid; delete it and reinstall",
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise invalid from None
    if not isinstance(data, dict) or any(
        key not in data for key in _MANIFEST_REQUIRED
    ):
        raise invalid
    if data["v"] != MANIFEST_VERSION:
        raise TmtError(
            "check-failed",
            f"integration manifest {path} has unsupported version "
            f"{data['v']!r}; this tmt supports v{MANIFEST_VERSION}",
        )
    if (
        not isinstance(data["entry"], dict)
        or not isinstance(data["created_file"], bool)
        or not isinstance(data["created_containers"], list)
    ):
        raise invalid
    return data


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmt-tmp")
    staging.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    staging.chmod(0o600)
    os.replace(staging, path)


def _drift_error(settings: Path) -> TmtError:
    return TmtError(
        "drift",
        f"the tmt-owned SessionStart hook in {settings} no longer matches "
        "the ownership manifest; run `tmt integration uninstall claude` "
        "and reinstall, or fix the settings file manually and delete "
        f"{manifest_path()}",
    )


def _assess() -> dict[str, Any]:
    """Shared state read for plan and install (no mutation)."""
    settings = settings_path()
    desired = hook_entry()
    manifest = _load_manifest(manifest_path())
    document = _load_settings(settings)
    groups = _groups(settings, document)
    state: str
    if manifest is None:
        present = any(_equal(group, desired) for group in groups)
        state = "adopt" if present else "install"
    elif any(_equal(group, manifest["entry"]) for group in groups):
        state = "ok" if _equal(manifest["entry"], desired) else "update"
    else:
        state = "drift"
    return {
        "desired": desired,
        "document": document,
        "groups": groups,
        "manifest": manifest,
        "settings": settings,
        "state": state,
    }


def plan() -> dict[str, Any]:
    """What install would change; performs no mutation."""
    assessment = _assess()
    state = assessment["state"]
    return {
        "changed": state in ("install", "update"),
        "entry": assessment["desired"],
        "settings": str(assessment["settings"]),
        "status": state,
    }


def install() -> dict[str, Any]:
    """Idempotently install the owned hook; refuse on drift."""
    assessment = _assess()
    settings: Path = assessment["settings"]
    desired = assessment["desired"]
    document = assessment["document"]
    state = assessment["state"]
    manifest = assessment["manifest"]
    if state == "drift":
        raise _drift_error(settings)
    changed = False
    created_file = manifest["created_file"] if manifest else False
    created_containers = list(
        manifest["created_containers"]
    ) if manifest else []
    if state == "install":
        created_file = not settings.is_file()
        if _HOOKS_KEY not in document:
            document[_HOOKS_KEY] = {}
            created_containers.append(_HOOKS_KEY)
        if _EVENT_KEY not in document[_HOOKS_KEY]:
            document[_HOOKS_KEY][_EVENT_KEY] = []
            created_containers.append(f"{_HOOKS_KEY}.{_EVENT_KEY}")
        document[_HOOKS_KEY][_EVENT_KEY].append(desired)
        _write_settings(settings, document)
        changed = True
    elif state == "update":
        groups = assessment["groups"]
        owned = assessment["manifest"]["entry"]
        for index, group in enumerate(groups):
            if _equal(group, owned):
                groups[index] = desired
                break
        _write_settings(settings, document)
        changed = True
    _write_manifest(
        manifest_path(),
        {
            "created_containers": created_containers,
            "created_file": created_file,
            "entry": desired,
            "integration": "claude",
            "scope": "user",
            "settings": str(settings),
            "v": MANIFEST_VERSION,
        },
    )
    return {
        "changed": changed,
        "entry": desired,
        "manifest": str(manifest_path()),
        "settings": str(settings),
        "status": "installed",
    }


def check() -> dict[str, Any]:
    """Report ok | absent | drifted without mutating anything."""
    settings = settings_path()
    result = {"settings": str(settings), "status": "absent"}
    manifest = _load_manifest(manifest_path())
    if manifest is None:
        return result
    try:
        document = _load_settings(settings)
        groups = _groups(settings, document)
    except TmtError:
        return {**result, "status": "drifted"}
    if any(_equal(group, manifest["entry"]) for group in groups):
        return {**result, "status": "ok"}
    return {**result, "status": "drifted"}


def uninstall() -> dict[str, Any]:
    """Remove only the byte-identical owned entry; refuse on drift."""
    settings = settings_path()
    result: dict[str, Any] = {
        "changed": False,
        "removed": False,
        "settings": str(settings),
        "status": "uninstalled",
    }
    manifest = _load_manifest(manifest_path())
    if manifest is None:
        return result
    owned = manifest["entry"]
    document = _load_settings(settings)
    groups = _groups(settings, document)
    index = next(
        (i for i, group in enumerate(groups) if _equal(group, owned)), None
    )
    if index is None:
        tampered = any(
            isinstance(group, dict)
            and group.get("matcher") == owned.get("matcher")
            for group in groups
        )
        if tampered:
            raise _drift_error(settings)
        manifest_path().unlink()
        return result
    del groups[index]
    created = set(manifest["created_containers"])
    hooks = document.get(_HOOKS_KEY)
    if (
        isinstance(hooks, dict)
        and f"{_HOOKS_KEY}.{_EVENT_KEY}" in created
        and hooks.get(_EVENT_KEY) == []
    ):
        del hooks[_EVENT_KEY]
    if _HOOKS_KEY in created and document.get(_HOOKS_KEY) == {}:
        del document[_HOOKS_KEY]
    if manifest["created_file"] and document == {} and settings.is_file():
        settings.unlink()
    else:
        _write_settings(settings, document)
    manifest_path().unlink()
    return {**result, "changed": True, "removed": True}

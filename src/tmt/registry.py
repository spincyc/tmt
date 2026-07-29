"""Load, validate, and save the committed tmt.json registry.

The hand-rolled validator mirrors the normative document
``schemas/tmt-v1.schema.json`` and stays stdlib-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REGISTRY_FILENAME = "tmt.json"
REGISTRY_VERSION = 1
ID_PATTERN = "^[a-z0-9][a-z0-9-]*$"
STAGES = ("draft", "stable")
PURPOSE_MAX_CHARS = 80

_ID_RE = re.compile(ID_PATTERN)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ENTRY_DEFAULTS: dict[str, Any] = {
    "idempotent": True,
    "json": False,
    "lang": "python",
    "mutates": False,
    "origin": "local",
    "requires": (),
}
_ENTRY_REQUIRED = ("purpose", "stage", "usage")
_ENTRY_KEYS = frozenset((*_ENTRY_REQUIRED, *ENTRY_DEFAULTS))
_ORIGIN_KEYS = ("commit", "repo", "sha256")
_ORIGIN_OPTIONAL_KEYS = ("url",)


class TmtError(Exception):
    """Failure carrying a stable machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def valid_id(tool_id: object) -> bool:
    return isinstance(tool_id, str) and _ID_RE.match(tool_id) is not None


def find_root(start: Path | None = None) -> Path | None:
    """Return the nearest directory at or above ``start`` holding tmt.json."""
    directory = (start or Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / REGISTRY_FILENAME).is_file():
            return candidate
    return None


def require_root(start: Path | None = None) -> Path:
    root = find_root(start)
    if root is None:
        raise TmtError(
            "no-registry",
            "no tmt.json found in this or any parent directory; run tmt init",
        )
    return root


def tool_path(root: Path, tool_id: str) -> Path:
    return root / "tools" / tool_id


def validate(data: Any) -> list[str]:
    """Return every validation failure; an empty list means valid."""
    if not isinstance(data, dict):
        return ["registry must be a JSON object"]
    errors: list[str] = []
    for key in sorted(set(data) - {"tools", "v"}):
        errors.append(f"unknown top-level key {key!r}")
    if "v" not in data:
        errors.append("missing required key 'v'")
    elif isinstance(data["v"], bool) or data["v"] != REGISTRY_VERSION:
        errors.append(f"'v' must be the integer {REGISTRY_VERSION}")
    if "tools" not in data:
        errors.append("missing required key 'tools'")
        return errors
    tools = data["tools"]
    if not isinstance(tools, dict):
        errors.append("'tools' must be a JSON object keyed by tool id")
        return errors
    for tool_id in sorted(tools):
        prefix = f"tools[{tool_id!r}]"
        if not valid_id(tool_id):
            errors.append(f"{prefix}: tool id must match {ID_PATTERN}")
        entry = tools[tool_id]
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: entry must be a JSON object")
            continue
        errors.extend(_validate_entry(prefix, entry))
    return errors


def _validate_entry(prefix: str, entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in sorted(set(entry) - _ENTRY_KEYS):
        errors.append(f"{prefix}.{key}: unknown key")
    for key in _ENTRY_REQUIRED:
        if key not in entry:
            errors.append(f"{prefix}.{key}: missing required key")
    if "purpose" in entry:
        purpose = entry["purpose"]
        if not isinstance(purpose, str):
            errors.append(f"{prefix}.purpose: must be a string")
        elif len(purpose) > PURPOSE_MAX_CHARS:
            errors.append(
                f"{prefix}.purpose: {len(purpose)} characters exceeds the "
                f"{PURPOSE_MAX_CHARS}-character cap"
            )
    if "usage" in entry and not isinstance(entry["usage"], str):
        errors.append(f"{prefix}.usage: must be a string")
    if "stage" in entry and entry["stage"] not in STAGES:
        errors.append(f"{prefix}.stage: must be one of: {', '.join(STAGES)}")
    if "lang" in entry and (
        not isinstance(entry["lang"], str) or not entry["lang"]
    ):
        errors.append(f"{prefix}.lang: must be a nonempty string")
    for key in ("idempotent", "json", "mutates"):
        if key in entry and not isinstance(entry[key], bool):
            errors.append(f"{prefix}.{key}: must be a boolean")
    if "requires" in entry:
        errors.extend(_validate_requires(prefix, entry["requires"]))
    if "origin" in entry:
        errors.extend(_validate_origin(prefix, entry["origin"]))
    return errors


def _validate_requires(prefix: str, requires: Any) -> list[str]:
    if not isinstance(requires, list):
        return [f"{prefix}.requires: must be an array of tool ids"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, dependency in enumerate(requires):
        if not valid_id(dependency):
            errors.append(
                f"{prefix}.requires[{index}]: must be a tool id "
                f"matching {ID_PATTERN}"
            )
        elif dependency in seen:
            errors.append(
                f"{prefix}.requires[{index}]: duplicate id {dependency!r}"
            )
        else:
            seen.add(dependency)
    return errors


def _validate_origin(prefix: str, origin: Any) -> list[str]:
    if origin == "local":
        return []
    if not isinstance(origin, dict):
        return [
            f"{prefix}.origin: must be \"local\" or an object with "
            "repo, commit, and sha256"
        ]
    errors: list[str] = []
    known = set(_ORIGIN_KEYS) | set(_ORIGIN_OPTIONAL_KEYS)
    for key in sorted(set(origin) - known):
        errors.append(f"{prefix}.origin.{key}: unknown key")
    for key in _ORIGIN_KEYS:
        if key not in origin:
            errors.append(f"{prefix}.origin.{key}: missing required key")
        elif not isinstance(origin[key], str) or not origin[key]:
            errors.append(f"{prefix}.origin.{key}: must be a nonempty string")
    for key in _ORIGIN_OPTIONAL_KEYS:
        if key in origin and (
            not isinstance(origin[key], str) or not origin[key]
        ):
            errors.append(f"{prefix}.origin.{key}: must be a nonempty string")
    sha256 = origin.get("sha256")
    if isinstance(sha256, str) and sha256 and not _SHA256_RE.match(sha256):
        errors.append(
            f"{prefix}.origin.sha256: must be 64 lowercase hex characters"
        )
    return errors


def load(root: Path) -> dict[str, Any]:
    """Parse and validate ``root``/tmt.json, raising TmtError on any defect."""
    path = root / REGISTRY_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise TmtError(
            "no-registry", f"{path} does not exist; run tmt init"
        ) from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise TmtError(
            "check-failed", f"tmt.json does not parse: {error}"
        ) from error
    errors = validate(data)
    if errors:
        summary = errors[0]
        if len(errors) > 1:
            summary += f" (+{len(errors) - 1} more; run tmt check)"
        raise TmtError("check-failed", f"tmt.json is invalid: {summary}")
    return data


def save(root: Path, data: dict[str, Any]) -> None:
    """Serialize per contract: key-sorted, 2-space indent, trailing newline."""
    (root / REGISTRY_FILENAME).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def effective(entry: dict[str, Any]) -> dict[str, Any]:
    """Return ``entry`` with schema defaults filled in."""
    merged = {**ENTRY_DEFAULTS, **entry}
    merged["requires"] = list(merged["requires"])
    return merged

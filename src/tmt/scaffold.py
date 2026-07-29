"""Create registries (init) and born-check-passing tools (new)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from tmt import registry
from tmt.registry import TmtError

LANGS = ("python", "sh")
DEFAULT_LANG = "python"
_TEMPLATE_FILES = {"python": "tool.py", "sh": "tool.sh"}
_TEST_TEMPLATE_FILE = "tool.test"

AGENTS_STANZA = (
    "Repo tools are indexed in tmt.json; run `tools/<id> --help` before "
    "re-deriving logic.",
    "Add tools with `tmt new <id>` and keep the registry honest with "
    "`tmt check`.",
)


def init(directory: Path) -> Path:
    """Create an empty tmt.json in ``directory``."""
    path = directory / registry.REGISTRY_FILENAME
    if path.exists():
        raise TmtError("already-exists", f"{path} already exists")
    registry.save(directory, {"tools": {}, "v": registry.REGISTRY_VERSION})
    return path


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _escape_python(value: str) -> str:
    """Escape for substitution inside a double-quoted Python string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_sh(value: str) -> str:
    """Escape for substitution inside a single-quoted sh word."""
    return value.replace("'", "'\\''")


def _template(filename: str) -> str:
    return (
        resources.files("tmt._resources")
        .joinpath("templates")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


def _render(lang: str, tool_id: str, purpose: str, usage: str) -> str:
    template = _template(_TEMPLATE_FILES[lang])
    escape = _escape_python if lang == "python" else _escape_sh
    for placeholder, value in (
        ("__TOOL_ID__", tool_id),
        ("__PURPOSE__", escape(purpose)),
        ("__USAGE__", escape(usage)),
    ):
        template = template.replace(placeholder, value)
    return template


def new(
    root: Path,
    tool_id: str,
    *,
    lang: str = DEFAULT_LANG,
    purpose: str | None = None,
    usage: str | None = None,
) -> dict[str, Any]:
    """Scaffold tools/<id>, a born-passing tools/<id>.test smoke test, and
    the draft tmt.json entry."""
    if not registry.valid_id(tool_id):
        raise TmtError(
            "usage",
            f"invalid tool id {tool_id!r}: must match {registry.ID_PATTERN}",
        )
    if lang not in LANGS:
        raise TmtError(
            "usage",
            f"unsupported scaffold lang {lang!r}: choose python or sh",
        )
    data = registry.load(root)
    if tool_id in data["tools"]:
        raise TmtError(
            "already-exists",
            f"tool {tool_id!r} is already registered in tmt.json",
        )
    path = registry.tool_path(root, tool_id)
    if path.exists():
        raise TmtError("already-exists", f"{path} already exists")
    if purpose is not None:
        purpose = _single_line(purpose)
        if len(purpose) > registry.PURPOSE_MAX_CHARS:
            raise TmtError(
                "usage",
                f"purpose is {len(purpose)} characters; the cap is "
                f"{registry.PURPOSE_MAX_CHARS}",
            )
    else:
        purpose = f"TODO: describe {tool_id}"[: registry.PURPOSE_MAX_CHARS]
    usage = (
        _single_line(usage) if usage is not None else f"tools/{tool_id} [--json]"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(lang, tool_id, purpose, usage), encoding="utf-8")
    path.chmod(0o755)
    test_path = path.with_name(f"{tool_id}.test")
    test_path.write_text(
        _template(_TEST_TEMPLATE_FILE).replace("__TOOL_ID__", tool_id),
        encoding="utf-8",
    )
    test_path.chmod(0o755)
    entry: dict[str, Any] = {
        "idempotent": True,
        "json": True,
        "lang": lang,
        "mutates": False,
        "origin": "local",
        "purpose": purpose,
        "requires": [],
        "stage": "draft",
        "usage": usage,
    }
    data["tools"][tool_id] = entry
    registry.save(root, data)
    return {
        "entry": entry,
        "id": tool_id,
        "lang": lang,
        "path": str(path.relative_to(root)),
        "test_path": str(test_path.relative_to(root)),
    }

"""Create registries (init) and born-check-passing tools (new)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from tmt import paths, registry
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
    paths.refuse_existing(path)
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


def render_test(tool_id: str) -> str:
    """The exact scaffolded ``tools/<id>.test`` content for ``tool_id``.

    The stable gate compares the on-disk test against this render to
    refuse promoting a tool whose test is still the unmodified scaffold.
    """
    return _template(_TEST_TEMPLATE_FILE).replace("__TOOL_ID__", tool_id)


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
    with registry.updating(root) as data:
        if tool_id in data["tools"]:
            raise TmtError(
                "already-exists",
                f"tool {tool_id!r} is already registered in tmt.json",
            )
        path = registry.tool_path(root, tool_id)
        paths.refuse_existing(path)
        test_path = path.with_name(f"{tool_id}.test")
        paths.refuse_existing(test_path)
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
            _single_line(usage)
            if usage is not None
            else f"tools/{tool_id} [--json]"
        )
        paths.resolve_within(root, path.parent, label="tools directory")
        paths.make_directory(path.parent)
        paths.write_new(
            path,
            _render(lang, tool_id, purpose, usage),
            mode=paths.EXECUTABLE_FILE_MODE,
        )
        paths.write_new(
            test_path, render_test(tool_id), mode=paths.EXECUTABLE_FILE_MODE
        )
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
    return {
        "entry": entry,
        "id": tool_id,
        "lang": lang,
        "path": str(path.relative_to(root)),
        "test_path": str(test_path.relative_to(root)),
    }

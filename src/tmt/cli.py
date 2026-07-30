"""tmt command-line interface.

Adopts the aiq cli-v1 protocol wholesale: with ``--json``, success is exactly
one compact key-sorted JSON object plus newline on stdout with top-level
``"v": 1``; failure is ``{"code","error","status":"error","v":1}`` on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from tmt import (
    __version__,
    agentsmd,
    aiqbridge,
    checks,
    claudehook,
    edits,
    notestore,
    paths,
    registry,
    scaffold,
    sessioncontext,
    transfer,
)
from tmt.registry import TmtError

PROTOCOL_VERSION = 1
NEW_TOOL_THRESHOLD = 2  # note count at which `tmt new` is suggested

# Exit categories: 0 ok, 1 check failures found (tmt check only), 2 usage,
# 3 state/environment, 70 internal.
EXIT_CODES = {
    "usage": 2,
    "not-found": 3,
    "already-exists": 3,
    "no-registry": 3,
    "check-failed": 3,
    "aiq-unavailable": 3,
    "portability": 3,
    "drift": 3,
    "containment": 3,
    "io-error": 3,
    "internal": 70,
}
STDIN_DRAIN_SECONDS = 0.5
_STDIN_DRAIN_BYTES = 1024 * 1024
_JSON_HELP = "emit one compact key-sorted cli-v1 JSON object"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        if "--json" in sys.argv[1:]:
            _emit_error("usage", message, as_json=True)
        else:
            print(f"{self.prog}: {_single_line(message)}", file=sys.stderr)
        raise SystemExit(2)


def _escape(character: str) -> str:
    """A JSON-style escape wide enough for astral characters."""
    code = ord(character)
    return f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}"


def _single_line(value: str) -> str:
    return "".join(
        character
        if character.isprintable() and character not in {"\t", "\r", "\n"}
        else _escape(character)
        for character in value
    )


def _terminal_safe(text: str) -> str:
    """Drop control characters a tool's own output could weaponize."""
    return "".join(
        character
        if character in {"\n", "\t"} or character.isprintable()
        else _escape(character)
        for character in text
    )


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {"v": PROTOCOL_VERSION, **payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def _emit_error(code: str, message: str, *, as_json: bool) -> None:
    safe_message = _single_line(message)
    if as_json:
        print(
            json.dumps(
                {
                    "code": code,
                    "error": safe_message,
                    "status": "error",
                    "v": PROTOCOL_VERSION,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
    else:
        print(f"tmt: {safe_message}", file=sys.stderr)


def _init(arguments: argparse.Namespace) -> int:
    path = scaffold.init(Path.cwd())
    agents = agentsmd.write(Path.cwd()) if arguments.agents else None
    if arguments.json:
        payload: dict[str, Any] = {
            "path": os.fspath(path),
            "stanza": list(scaffold.AGENTS_STANZA),
            "status": "initialized",
        }
        if agents is not None:
            payload["agents"] = agents
        _emit(payload, as_json=True)
        return 0
    for line in scaffold.AGENTS_STANZA:
        print(line)
    if agents is not None:
        print("AGENTS.md: installed")
    return 0


def _agents(arguments: argparse.Namespace) -> int:
    root = registry.require_root()
    if arguments.write:
        result = agentsmd.write(root)
        if arguments.json:
            _emit(result, as_json=True)
        elif result["changed"]:
            print(f"AGENTS.md: {result['previous']} -> installed")
        else:
            print("AGENTS.md already installed")
        return 0
    result = agentsmd.status(root)
    if arguments.json:
        _emit(result, as_json=True)
    else:
        print(result["status"])
    return 0


def _drain_stdin() -> None:
    """Consume a hook's piped JSON without ever blocking on it.

    An agent shell hands the command an open stdin that nobody writes to,
    so an unbounded read would hang the session this must never break.
    """
    import select

    descriptor = sys.stdin.fileno()
    deadline = time.monotonic() + STDIN_DRAIN_SECONDS
    read = 0
    while read < _STDIN_DRAIN_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        ready, _, _ = select.select([descriptor], [], [], remaining)
        if not ready:
            return
        chunk = os.read(descriptor, 65536)
        if not chunk:
            return
        read += len(chunk)


def _context(arguments: argparse.Namespace) -> int:
    # Fail-open is the hard requirement: this hook payload must never
    # break a session, so every failure path still exits 0 in silence.
    try:
        if not sys.stdin.isatty():
            _drain_stdin()
    except Exception:
        pass
    try:
        for line in sessioncontext.build(Path.cwd()):
            print(line)
    except Exception:
        pass
    return 0


def _integration_print(arguments: argparse.Namespace) -> int:
    if arguments.target == "agents":
        if arguments.integration_id is not None:
            raise TmtError(
                "usage", "print agents does not take an integration id"
            )
        if arguments.json:
            _emit(
                {
                    "fragment": agentsmd.FRAGMENT,
                    "fragment_version": agentsmd.FRAGMENT_VERSION,
                },
                as_json=True,
            )
            return 0
        print(agentsmd.FRAGMENT)
        return 0
    if arguments.integration_id == "generic":
        fragment = sessioncontext.GENERIC_HOOK_FRAGMENT
        if arguments.json:
            _emit(
                {"command": sessioncontext.HOOK_COMMAND, "fragment": fragment},
                as_json=True,
            )
            return 0
        sys.stdout.write(fragment)
        return 0
    if arguments.integration_id != "claude":
        raise TmtError(
            "usage",
            "print hook requires the integration 'claude' or 'generic'",
        )
    fragment = claudehook.settings_fragment()
    if arguments.json:
        _emit({"fragment": fragment}, as_json=True)
        return 0
    print(json.dumps(fragment, ensure_ascii=False, indent=2))
    return 0


def _integration_plan(arguments: argparse.Namespace) -> int:
    result = claudehook.plan()
    if arguments.json:
        _emit(result, as_json=True)
        return 0
    settings = result["settings"]
    if result["status"] == "drift" and result["mismatch"]:
        print(
            f"drift: tmt owns the hook in {settings}, but this environment "
            "resolves a different settings file"
        )
        return 0
    summary = {
        "install": f"would add the SessionStart hook to {settings}",
        "update": f"would update the tmt-owned SessionStart hook in {settings}",
        "adopt": f"entry already present in {settings}; would record ownership",
        "ok": f"already installed in {settings}",
        "drift": f"drift: the tmt-owned entry in {settings} was edited",
    }[result["status"]]
    print(summary)
    return 0


def _integration_install(arguments: argparse.Namespace) -> int:
    result = claudehook.install()
    if arguments.json:
        _emit(result, as_json=True)
    elif result["changed"]:
        print(f"installed the SessionStart hook in {result['settings']}")
    else:
        print(f"already installed in {result['settings']}")
    return 0


def _integration_check(arguments: argparse.Namespace) -> int:
    result = claudehook.check()
    if arguments.json:
        _emit(result, as_json=True)
    else:
        print(result["status"])
    return 0 if result["status"] == "ok" else 1


def _integration_uninstall(arguments: argparse.Namespace) -> int:
    result = claudehook.uninstall()
    if arguments.json:
        _emit(result, as_json=True)
    elif result["removed"]:
        print(f"removed the SessionStart hook from {result['settings']}")
    else:
        print("nothing installed")
    return 0


def _new(arguments: argparse.Namespace) -> int:
    result = scaffold.new(
        registry.require_root(),
        arguments.id,
        lang=arguments.lang,
        purpose=arguments.purpose,
        usage=arguments.usage,
    )
    if arguments.json:
        _emit(
            {
                "id": result["id"],
                "lang": result["lang"],
                "path": result["path"],
                "stage": "draft",
                "test_path": result["test_path"],
            },
            as_json=True,
        )
        return 0
    print(result["path"])
    print(result["test_path"])
    return 0


def _rm(arguments: argparse.Namespace) -> int:
    result = edits.remove(
        registry.require_root(), arguments.id, keep_files=arguments.keep_files
    )
    if arguments.json:
        _emit({**result, "status": "removed"}, as_json=True)
        return 0
    print(f"removed {result['id']}")
    for name in result["removed_files"]:
        print(f"deleted tools/{name}")
    return 0


def _rename(arguments: argparse.Namespace) -> int:
    result = edits.rename(
        registry.require_root(), arguments.id, arguments.new_id
    )
    if arguments.json:
        _emit({**result, "status": "renamed"}, as_json=True)
        return 0
    print(f"{result['previous']} -> {result['id']}")
    for other in result["updated_dependents"]:
        print(f"updated requires in {other}")
    for other in result["stale_callers"]:
        print(
            f"warning: {other} still calls '{result['previous']}' in its "
            "body; update it by hand"
        )
    return 0


def _set(arguments: argparse.Namespace) -> int:
    result = edits.set_field(
        registry.require_root(), arguments.id, arguments.field, arguments.value
    )
    if arguments.json:
        _emit({**result, "status": "set"}, as_json=True)
        return 0
    value = result["value"]
    if isinstance(value, list):
        value = ",".join(value)
    print(f"{result['id']}.{result['field']} = {_single_line(str(value))}")
    return 0


def _list(arguments: argparse.Namespace) -> int:
    data = registry.load(registry.require_root())
    rows = [
        {
            "id": tool_id,
            "purpose": entry["purpose"],
            "stage": entry["stage"],
        }
        for tool_id, entry in sorted(data["tools"].items())
        if arguments.stage is None
        or registry.effective(entry)["stage"] == arguments.stage
    ]
    if arguments.json:
        _emit({"tools": rows}, as_json=True)
        return 0
    for row in rows:
        print(
            f"{_single_line(row['id'])}\t{row['stage']}\t"
            f"{_single_line(row['purpose'])}"
        )
    return 0


def _read_doc(path: Path) -> str:
    """A tool's long doc, whose bytes tmt does not control."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise TmtError(
            "check-failed", f"{path} is not valid UTF-8: {error}"
        ) from error
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error


def _show(arguments: argparse.Namespace) -> int:
    root = registry.require_root()
    data = registry.load(root)
    raw = data["tools"].get(arguments.id)
    if raw is None:
        raise TmtError(
            "not-found", f"tool {arguments.id!r} is not registered in tmt.json"
        )
    entry = registry.effective(raw)
    tool = registry.tool_path(root, arguments.id)
    help_text: str | None = None
    if tool.is_file():
        # show executes the tool and reads its doc, so both must be the
        # repository's own files — `tmt check` gates the executable, and
        # showing one is no less an execution.
        paths.resolve_within(root, tool, label=f"tools/{arguments.id}")
        ok, captured = checks.capture_help(tool)
        if ok:
            help_text = captured
    doc_path = tool.with_name(f"{tool.name}.md")
    doc = None
    if doc_path.is_file():
        paths.resolve_within(
            root, doc_path, label=f"tools/{arguments.id}.md"
        )
        doc = _read_doc(doc_path)
    if arguments.json:
        _emit(
            {"doc": doc, "entry": entry, "help": help_text, "id": arguments.id},
            as_json=True,
        )
        return 0
    for key in sorted(entry):
        value: Any = entry[key]
        if key in ("config", "requires"):
            value = ",".join(value)
        elif key == "origin" and isinstance(value, dict):
            value = f"{value['repo']}@{value['commit']}"
        if isinstance(value, str):
            value = _single_line(value)
        print(f"{key}\t{value}")
    for block in (help_text, doc):
        if block is not None:
            safe = _terminal_safe(block)
            print()
            sys.stdout.write(safe if safe.endswith("\n") else safe + "\n")
    return 0


def _check(arguments: argparse.Namespace) -> int:
    root = registry.require_root()
    if arguments.id is None:
        failures, warnings = checks.run_checks(root)
    else:
        failures, warnings = checks.run_tool_checks(root, arguments.id)
    status = "ok" if not failures else "failed"
    if arguments.json:
        payload: dict[str, Any] = {
            "failures": failures,
            "status": status,
            "warnings": warnings,
        }
        if arguments.id is not None:
            payload["id"] = arguments.id
        _emit(payload, as_json=True)
    else:
        for failure in failures:
            print(f"FAIL {_single_line(failure)}")
        for warning in warnings:
            print(f"WARN {_single_line(warning)}")
        if status == "ok":
            print("ok")
    return 0 if status == "ok" else 1


def _stage(arguments: argparse.Namespace) -> int:
    root = registry.require_root()
    data = registry.load(root)
    tools = data["tools"]
    entry = tools.get(arguments.id)
    if entry is None:
        raise TmtError(
            "not-found", f"tool {arguments.id!r} is not registered in tmt.json"
        )
    previous = registry.effective(entry)["stage"]
    target = arguments.stage
    changed = previous != target
    if changed and target == "stable":
        failures = checks.stable_gate_failures(root, arguments.id, tools)
        if failures:
            raise TmtError(
                "check-failed",
                f"cannot promote {arguments.id!r} to stable: "
                + "; ".join(failures),
            )
    if changed and target == "draft":
        dependents = sorted(
            other
            for other, raw in tools.items()
            if other != arguments.id
            and registry.effective(raw)["stage"] == "stable"
            and arguments.id in registry.effective(raw)["requires"]
        )
        if dependents:
            raise TmtError(
                "check-failed",
                f"cannot demote {arguments.id!r} to draft: required by "
                f"stable {', '.join(dependents)}",
            )
    if changed:
        entry["stage"] = target
        registry.save(root, data)
    if arguments.json:
        _emit(
            {
                "changed": changed,
                "id": arguments.id,
                "previous": previous,
                "stage": target,
            },
            as_json=True,
        )
        return 0
    if changed:
        print(f"{arguments.id}: {previous} -> {target}")
    else:
        print(f"{arguments.id} already {target}")
    return 0


def _registered_tools(root: Path | None) -> set[str]:
    if root is None:
        return set()
    try:
        return set(registry.load(root)["tools"])
    except TmtError:
        return set()


def _note(arguments: argparse.Namespace) -> int:
    if not registry.valid_id(arguments.slug):
        raise TmtError(
            "usage",
            f"invalid slug {arguments.slug!r}: must match "
            f"{registry.ID_PATTERN}",
        )
    root = registry.find_root()
    cwd = root or Path.cwd()
    # A slug that is already a tool needs no note: the loop is done.
    if arguments.slug in _registered_tools(root):
        if arguments.json:
            _emit(
                {"built": True, "recorded": False, "slug": arguments.slug},
                as_json=True,
            )
            return 0
        print(
            f"'{arguments.slug}' is already a tool; "
            f"run tools/{arguments.slug} --help"
        )
        return 0
    count = notestore.append(cwd, arguments.slug, arguments.note)
    # aiq is the optional upgrade: mirroring must never fail the note.
    mirrored: str | None = None
    try:
        mirrored = aiqbridge.note(arguments.slug, arguments.note, cwd=cwd)[
            "message_id"
        ]
    except TmtError:
        mirrored = None
    if arguments.json:
        payload: dict[str, Any] = {
            "built": False,
            "count": count,
            "message_id": mirrored,
            "recorded": True,
            "slug": arguments.slug,
        }
        _emit(payload, as_json=True)
        return 0
    noun = "note" if count == 1 else "notes"
    feedback = f"{count} {noun} for '{arguments.slug}'"
    if count >= NEW_TOOL_THRESHOLD:
        feedback += f" — consider `tmt new {arguments.slug}`"
    print(feedback)
    return 0


def _candidates(arguments: argparse.Namespace) -> int:
    root = registry.find_root()
    cwd = root or Path.cwd()
    if arguments.dismiss is not None:
        removed = notestore.dismiss(cwd, arguments.dismiss)
        if arguments.json:
            _emit(
                {"dismissed": removed, "slug": arguments.dismiss},
                as_json=True,
            )
            return 0
        print(f"dismissed {removed} for '{arguments.dismiss}'")
        return 0
    built = _registered_tools(root)
    rows = [
        {**row, "built": row["slug"] in built}
        for row in notestore.counts(cwd)
    ]
    if arguments.json:
        _emit({"candidates": rows}, as_json=True)
        return 0
    for row in rows:
        suffix = "\tbuilt" if row["built"] else ""
        print(f"{row['count']}\t{_single_line(row['slug'])}{suffix}")
    return 0


def _vendor(arguments: argparse.Namespace) -> int:
    result = transfer.vendor(
        registry.require_root(), arguments.source, arguments.id
    )
    if arguments.json:
        _emit({**result, "status": "vendored"}, as_json=True)
        return 0
    print(result["path"])
    if "config" in result:
        paths = ", ".join(result["config"])
        print(f"note: reads {_single_line(paths)}; create them in this repo")
    return 0


def _adopt(arguments: argparse.Namespace) -> int:
    result = transfer.adopt(
        registry.require_root(), arguments.id, arguments.to
    )
    if arguments.json:
        _emit({**result, "status": "adopted"}, as_json=True)
        return 0
    print(f"{result['id']} -> {result['to']}")
    if "config" in result:
        paths = ", ".join(result["config"])
        print(
            f"note: reads {_single_line(paths)}; create them in the "
            "destination repo"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="tmt",
        description="Make, index, compose, and promote repo-local tools.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init", help="create tmt.json and print the AGENTS.md stanza"
    )
    init.add_argument(
        "--agents",
        action="store_true",
        help="also install the AGENTS.md fragment block",
    )
    init.add_argument("--json", action="store_true", help=_JSON_HELP)
    init.set_defaults(handler=_init)

    agents = commands.add_parser(
        "agents", help="report or install the AGENTS.md habit fragment"
    )
    agents.add_argument(
        "--write",
        action="store_true",
        help="create AGENTS.md or insert/replace the marker block",
    )
    agents.add_argument("--json", action="store_true", help=_JSON_HELP)
    agents.set_defaults(handler=_agents)

    context = commands.add_parser(
        "context",
        help="print session context for hooks (plain text, always exit 0)",
    )
    context.set_defaults(handler=_context)

    integration = commands.add_parser(
        "integration", help="manage session-integration surfaces"
    )
    integration_commands = integration.add_subparsers(
        dest="integration_command", required=True
    )
    integration_print = integration_commands.add_parser(
        "print", help="print the AGENTS.md fragment or a hook fragment"
    )
    integration_print.add_argument(
        "target",
        choices=("agents", "hook"),
        metavar="TARGET",
        help="agents (the AGENTS.md fragment) or hook",
    )
    integration_print.add_argument(
        "integration_id",
        nargs="?",
        metavar="INTEGRATION",
        help="for hook: claude (settings JSON) or generic (shell snippet)",
    )
    integration_print.add_argument(
        "--json", action="store_true", help=_JSON_HELP
    )
    integration_print.set_defaults(handler=_integration_print)
    for name, handler, help_text in (
        ("plan", _integration_plan, "preview the owned settings change"),
        ("install", _integration_install, "install the owned hook entry"),
        ("check", _integration_check, "report ok, absent, or drifted"),
        ("uninstall", _integration_uninstall, "remove the owned hook entry"),
    ):
        lifecycle = integration_commands.add_parser(name, help=help_text)
        lifecycle.add_argument(
            "integration_id", choices=("claude",), metavar="INTEGRATION"
        )
        lifecycle.add_argument(
            "--user",
            action="store_true",
            help="user scope (the default and only scope)",
        )
        lifecycle.add_argument("--json", action="store_true", help=_JSON_HELP)
        lifecycle.set_defaults(handler=handler)

    new = commands.add_parser(
        "new",
        help="scaffold tools/<id>, its smoke test, and a draft entry",
    )
    new.add_argument("id", help=f"new tool id matching {registry.ID_PATTERN}")
    new.add_argument(
        "--lang", choices=scaffold.LANGS, default=scaffold.DEFAULT_LANG
    )
    new.add_argument("--purpose", metavar="TEXT")
    new.add_argument("--usage", metavar="TEXT")
    new.add_argument("--json", action="store_true", help=_JSON_HELP)
    new.set_defaults(handler=_new)

    remove = commands.add_parser(
        "rm", help="delete a tool's entry and its files"
    )
    remove.add_argument("id", help="registered tool id")
    remove.add_argument(
        "--keep-files",
        action="store_true",
        help="unregister only; leave tools/<id> on disk",
    )
    remove.add_argument("--json", action="store_true", help=_JSON_HELP)
    remove.set_defaults(handler=_rm)

    rename = commands.add_parser(
        "rename", help="rename a tool, its files, and every dependent"
    )
    rename.add_argument("id", help="registered tool id")
    rename.add_argument(
        "new_id",
        metavar="NEW_ID",
        help=f"new id matching {registry.ID_PATTERN}",
    )
    rename.add_argument("--json", action="store_true", help=_JSON_HELP)
    rename.set_defaults(handler=_rename)

    set_field = commands.add_parser(
        "set", help="set one entry field, validated before saving"
    )
    set_field.add_argument("id", help="registered tool id")
    set_field.add_argument(
        "field",
        choices=edits.SETTABLE_FIELDS,
        metavar="FIELD",
        help=f"one of: {', '.join(edits.SETTABLE_FIELDS)}",
    )
    set_field.add_argument(
        "value",
        metavar="VALUE",
        help="true/false for flags, comma-separated for lists",
    )
    set_field.add_argument("--json", action="store_true", help=_JSON_HELP)
    set_field.set_defaults(handler=_set)

    list_tools = commands.add_parser(
        "list", help="one line per tool: id, stage, purpose"
    )
    list_tools.add_argument(
        "--stage",
        choices=registry.STAGES,
        help="list only tools at this stage",
    )
    list_tools.add_argument("--json", action="store_true", help=_JSON_HELP)
    list_tools.set_defaults(handler=_list)

    show = commands.add_parser(
        "show", help="entry, captured --help, and tools/<id>.md if present"
    )
    show.add_argument("id", help="registered tool id")
    show.add_argument("--json", action="store_true", help=_JSON_HELP)
    show.set_defaults(handler=_show)

    check = commands.add_parser(
        "check", help="run the gate battery; collect every failure"
    )
    check.add_argument(
        "id",
        nargs="?",
        help="gate only this tool instead of the whole repository",
    )
    check.add_argument("--json", action="store_true", help=_JSON_HELP)
    check.set_defaults(handler=_check)

    stage = commands.add_parser(
        "stage", help="promote or demote a tool through the stable gates"
    )
    stage.add_argument("id", help="registered tool id")
    stage.add_argument(
        "stage",
        choices=registry.STAGES,
        metavar="STAGE",
        help=f"target stage: {' or '.join(registry.STAGES)}",
    )
    stage.add_argument("--json", action="store_true", help=_JSON_HELP)
    stage.set_defaults(handler=_stage)

    note = commands.add_parser(
        "note",
        help="record a re-derivation candidate (mirrored to aiq when present)",
    )
    note.add_argument("slug", help="what was re-derived, as a tool id")
    note.add_argument("--note", metavar="TEXT")
    note.add_argument("--json", action="store_true", help=_JSON_HELP)
    note.set_defaults(handler=_note)

    candidates = commands.add_parser(
        "candidates", help="count recorded candidates, most-noted first"
    )
    candidates.add_argument(
        "--dismiss",
        metavar="SLUG",
        help="forget every note recorded for SLUG",
    )
    candidates.add_argument("--json", action="store_true", help=_JSON_HELP)
    candidates.set_defaults(handler=_candidates)

    vendor = commands.add_parser(
        "vendor", help="copy a tool in from another repo, stamping origin"
    )
    vendor.add_argument(
        "source",
        type=Path,
        metavar="SOURCE_REPO",
        help="path to the tmt-enabled repo to copy from",
    )
    vendor.add_argument("id", help="tool id registered in SOURCE_REPO")
    vendor.add_argument("--json", action="store_true", help=_JSON_HELP)
    vendor.set_defaults(handler=_vendor)

    adopt = commands.add_parser(
        "adopt", help="portability-lint a tool, then copy it out to a repo"
    )
    adopt.add_argument("id", help="stable tool id in this repo")
    adopt.add_argument("--to", type=Path, required=True, metavar="DEST_REPO")
    adopt.add_argument("--json", action="store_true", help=_JSON_HELP)
    adopt.set_defaults(handler=_adopt)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    as_json = getattr(arguments, "json", False)
    try:
        return arguments.handler(arguments)
    except TmtError as error:
        _emit_error(error.code, str(error), as_json=as_json)
        return EXIT_CODES.get(error.code, 70)
    except KeyboardInterrupt:
        _emit_error("io-error", "interrupted", as_json=as_json)
        return 130
    except OSError as error:  # environment, not a tmt defect
        _emit_error("io-error", str(error), as_json=as_json)
        return EXIT_CODES["io-error"]
    except Exception as error:  # defect boundary: never a traceback in JSON
        _emit_error(
            "internal",
            str(error) or error.__class__.__name__,
            as_json=as_json,
        )
        return 70

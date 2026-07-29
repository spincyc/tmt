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
from pathlib import Path
from typing import Any, Mapping, Sequence

from tmt import (
    __version__,
    agentsmd,
    aiqbridge,
    checks,
    claudehook,
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
    "internal": 70,
}


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        if "--json" in sys.argv[1:]:
            _emit_error("usage", message, as_json=True)
        else:
            print(f"{self.prog}: {_single_line(message)}", file=sys.stderr)
        raise SystemExit(2)


def _single_line(value: str) -> str:
    return "".join(
        character
        if character.isprintable() and character not in {"\t", "\r", "\n"}
        else f"\\u{ord(character):04x}"
        for character in value
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


def _context(arguments: argparse.Namespace) -> int:
    # Fail-open is the hard requirement: this hook payload must never
    # break a session, so every failure path still exits 0 in silence.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()  # hooks pipe JSON; consume and ignore it
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
    if arguments.integration_id != "claude":
        raise TmtError("usage", "print hook requires the integration 'claude'")
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


def _list(arguments: argparse.Namespace) -> int:
    data = registry.load(registry.require_root())
    rows = [
        {
            "id": tool_id,
            "purpose": entry["purpose"],
            "stage": entry["stage"],
        }
        for tool_id, entry in sorted(data["tools"].items())
    ]
    if arguments.json:
        _emit({"tools": rows}, as_json=True)
        return 0
    for row in rows:
        print(f"{row['id']}\t{row['stage']}\t{_single_line(row['purpose'])}")
    return 0


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
        ok, captured = checks.capture_help(tool)
        if ok:
            help_text = captured
    doc_path = tool.with_name(f"{tool.name}.md")
    doc = (
        doc_path.read_text(encoding="utf-8") if doc_path.is_file() else None
    )
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
            print()
            sys.stdout.write(block if block.endswith("\n") else block + "\n")
    return 0


def _check(arguments: argparse.Namespace) -> int:
    failures, warnings = checks.run_checks(registry.require_root())
    status = "ok" if not failures else "failed"
    if arguments.json:
        _emit(
            {"failures": failures, "status": status, "warnings": warnings},
            as_json=True,
        )
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


def _note(arguments: argparse.Namespace) -> int:
    if not registry.valid_id(arguments.slug):
        raise TmtError(
            "usage",
            f"invalid slug {arguments.slug!r}: must match "
            f"{registry.ID_PATTERN}",
        )
    cwd = registry.find_root() or Path.cwd()
    result = aiqbridge.note(arguments.slug, arguments.note, cwd=cwd)
    # The ingest succeeded; a count problem must never fail the note.
    count = aiqbridge.slug_count(arguments.slug, cwd=cwd)
    if arguments.json:
        payload: dict[str, Any] = {
            "created": result["created"],
            "message_id": result["message_id"],
            "slug": arguments.slug,
        }
        if count is not None:
            payload["count"] = count
        _emit(payload, as_json=True)
        return 0
    print(result["message_id"])
    if count is not None:
        noun = "note" if count == 1 else "notes"
        feedback = f"{count} {noun} for '{arguments.slug}'"
        if count >= NEW_TOOL_THRESHOLD:
            feedback += f" — consider `tmt new {arguments.slug}`"
        print(feedback)
    return 0


def _candidates(arguments: argparse.Namespace) -> int:
    cwd = registry.find_root() or Path.cwd()
    rows = aiqbridge.candidates(cwd=cwd)
    if arguments.json:
        _emit({"candidates": rows}, as_json=True)
        return 0
    for row in rows:
        print(f"{row['count']}\t{row['slug']}")
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
    init.add_argument("--json", action="store_true")
    init.set_defaults(handler=_init)

    agents = commands.add_parser(
        "agents", help="report or install the AGENTS.md habit fragment"
    )
    agents.add_argument(
        "--write",
        action="store_true",
        help="create AGENTS.md or insert/replace the marker block",
    )
    agents.add_argument("--json", action="store_true")
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
        "target", choices=("agents", "hook"), metavar="TARGET"
    )
    integration_print.add_argument(
        "integration_id", nargs="?", metavar="INTEGRATION"
    )
    integration_print.add_argument("--json", action="store_true")
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
        lifecycle.add_argument("--json", action="store_true")
        lifecycle.set_defaults(handler=handler)

    new = commands.add_parser(
        "new",
        help="scaffold tools/<id>, its smoke test, and a draft entry",
    )
    new.add_argument("id")
    new.add_argument(
        "--lang", choices=scaffold.LANGS, default=scaffold.DEFAULT_LANG
    )
    new.add_argument("--purpose", metavar="TEXT")
    new.add_argument("--usage", metavar="TEXT")
    new.add_argument("--json", action="store_true")
    new.set_defaults(handler=_new)

    list_tools = commands.add_parser(
        "list", help="one line per tool: id, stage, purpose"
    )
    list_tools.add_argument("--json", action="store_true")
    list_tools.set_defaults(handler=_list)

    show = commands.add_parser(
        "show", help="entry, captured --help, and tools/<id>.md if present"
    )
    show.add_argument("id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(handler=_show)

    check = commands.add_parser(
        "check", help="run the full gate battery; collect every failure"
    )
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=_check)

    stage = commands.add_parser(
        "stage", help="promote or demote a tool through the stable gates"
    )
    stage.add_argument("id")
    stage.add_argument("stage", choices=registry.STAGES, metavar="STAGE")
    stage.add_argument("--json", action="store_true")
    stage.set_defaults(handler=_stage)

    note = commands.add_parser(
        "note", help="emit a tool-candidate event via aiq ingest"
    )
    note.add_argument("slug")
    note.add_argument("--note", metavar="TEXT")
    note.add_argument("--json", action="store_true")
    note.set_defaults(handler=_note)

    candidates = commands.add_parser(
        "candidates", help="group and count tmt-note events from aiq"
    )
    candidates.add_argument("--json", action="store_true")
    candidates.set_defaults(handler=_candidates)

    vendor = commands.add_parser(
        "vendor", help="copy a tool in from another repo, stamping origin"
    )
    vendor.add_argument("source", type=Path, metavar="SOURCE_REPO")
    vendor.add_argument("id")
    vendor.add_argument("--json", action="store_true")
    vendor.set_defaults(handler=_vendor)

    adopt = commands.add_parser(
        "adopt", help="portability-lint a tool, then copy it out to a repo"
    )
    adopt.add_argument("id")
    adopt.add_argument("--to", type=Path, required=True, metavar="DEST_REPO")
    adopt.add_argument("--json", action="store_true")
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
    except Exception as error:  # defect boundary: never a traceback in JSON
        _emit_error(
            "internal",
            str(error) or error.__class__.__name__,
            as_json=as_json,
        )
        return 70

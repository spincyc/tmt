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

from tmt import __version__, aiqbridge, checks, registry, scaffold, transfer
from tmt.registry import TmtError

PROTOCOL_VERSION = 1

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
    if arguments.json:
        _emit(
            {
                "path": os.fspath(path),
                "stanza": list(scaffold.AGENTS_STANZA),
                "status": "initialized",
            },
            as_json=True,
        )
        return 0
    for line in scaffold.AGENTS_STANZA:
        print(line)
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
            },
            as_json=True,
        )
        return 0
    print(result["path"])
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
        if key == "requires":
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


def _note(arguments: argparse.Namespace) -> int:
    if not registry.valid_id(arguments.slug):
        raise TmtError(
            "usage",
            f"invalid slug {arguments.slug!r}: must match "
            f"{registry.ID_PATTERN}",
        )
    cwd = registry.find_root() or Path.cwd()
    result = aiqbridge.note(arguments.slug, arguments.note, cwd=cwd)
    if arguments.json:
        _emit(
            {
                "created": result["created"],
                "message_id": result["message_id"],
                "slug": arguments.slug,
            },
            as_json=True,
        )
        return 0
    print(result["message_id"])
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
    return 0


def _adopt(arguments: argparse.Namespace) -> int:
    result = transfer.adopt(
        registry.require_root(), arguments.id, arguments.to
    )
    if arguments.json:
        _emit({**result, "status": "adopted"}, as_json=True)
        return 0
    print(f"{result['id']} -> {result['to']}")
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
    init.add_argument("--json", action="store_true")
    init.set_defaults(handler=_init)

    new = commands.add_parser(
        "new", help="scaffold tools/<id> plus a draft registry entry"
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

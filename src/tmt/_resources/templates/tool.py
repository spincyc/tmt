#!/usr/bin/env python3
"""__PURPOSE__

Usage: __USAGE__
"""
# Composition idiom: run a sibling tool with
#     subprocess.run([str(Path(__file__).parent / "<dep>"), ...], check=True)
# and declare "<dep>" in this tool's `requires` list in tmt.json.
from __future__ import annotations

import argparse
import json
import sys

PROTOCOL_VERSION = 1


def run() -> dict[str, object]:
    """Produce this tool's result. Replace the body with the derived logic."""
    return {"result": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="__TOOL_ID__",
        description="__PURPOSE__",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one compact key-sorted JSON object (cli-v1)",
    )
    arguments = parser.parse_args(argv)
    try:
        payload = run()
    except Exception as error:
        # cli-v1 error contract: exactly one compact key-sorted JSON object
        # on stderr, nothing on stdout, stable code plus exit category.
        message = str(error) or error.__class__.__name__
        if arguments.json:
            print(
                json.dumps(
                    {
                        "code": "internal",
                        "error": message,
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
            print(f"__TOOL_ID__: {message}", file=sys.stderr)
        return 70
    if arguments.json:
        print(
            json.dumps(
                {**payload, "v": PROTOCOL_VERSION},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    for key, value in payload.items():
        print(f"{key}\t{value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

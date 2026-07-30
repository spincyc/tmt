"""Local candidate notes, so the habit loop never requires aiq.

Notes are the front half of the loop: without a store of its own tmt
could only count them when aiq was installed, which made a stranger's
first `tmt note` an error. The store is untracked machine-local state in
``paths.state_dir`` — the repository's git common directory (aiq's
resolve_scope precedent), or ``.tmt/`` when the repository is not a git
work tree. aiq remains the optional upgrade: `tmt note` still mirrors
each note to aiq when it is available, and a mirroring failure never
fails the note.

Writing a note is a read-modify-write like every other tmt mutation, so
both writers hold ``paths.locked``; reading is lock-free, because `tmt
context` must never block on another process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tmt import paths
from tmt.registry import TmtError

NOTES_FILENAME = "notes.jsonl"


def store_path(root: Path) -> Path:
    return paths.state_dir(root) / NOTES_FILENAME


def _read(root: Path) -> list[dict[str, Any]]:
    path = store_path(root)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as error:
        raise TmtError("io-error", f"{path}: {error}") from error
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("slug"), str):
            records.append(record)
    return records


def append(root: Path, slug: str, note_text: str | None) -> int:
    """Record one note; return the slug's new count."""
    line = json.dumps(
        {"note": note_text, "slug": slug},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    path = store_path(root)
    # locked creates the state directory the note lands in, and keeps a
    # concurrent dismiss from rewriting the file around this append.
    with paths.locked(root):
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as error:
            raise TmtError("io-error", f"{path}: {error}") from error
        return sum(1 for record in _read(root) if record["slug"] == slug)


def counts(root: Path) -> list[dict[str, Any]]:
    """Slug groups, most-noted first, each with its recorded notes."""
    groups: dict[str, dict[str, Any]] = {}
    for record in _read(root):
        slug = record["slug"]
        group = groups.setdefault(
            slug, {"count": 0, "notes": [], "slug": slug}
        )
        group["count"] += 1
        note_text = record.get("note")
        if isinstance(note_text, str) and note_text:
            group["notes"].append(note_text)
    return sorted(
        groups.values(), key=lambda group: (-group["count"], group["slug"])
    )


def dismiss(root: Path, slug: str) -> int:
    """Drop every note for ``slug``; return how many were removed."""
    with paths.locked(root):
        records = _read(root)
        kept = [record for record in records if record["slug"] != slug]
        removed = len(records) - len(kept)
        if not removed:
            return 0
        lines = [
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for record in kept
        ]
        text = "".join(line + "\n" for line in lines)
        paths.write_atomic(store_path(root), text)
    return removed

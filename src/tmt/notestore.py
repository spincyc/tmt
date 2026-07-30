"""Local candidate notes, so the habit loop never requires aiq.

Notes are the front half of the loop: without a store of its own tmt
could only count them when aiq was installed, which made a stranger's
first `tmt note` an error. The store is untracked machine-local state
under the repository's git common directory (aiq's resolve_scope
precedent), or ``.tmt/`` when the repository is not a git work tree. aiq
remains the optional upgrade: `tmt note` still mirrors each note to aiq
when it is available, and a mirroring failure never fails the note.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tmt import paths
from tmt.registry import TmtError

STATE_DIRNAME = "tmt"
NOTES_FILENAME = "notes.jsonl"
FALLBACK_DIRNAME = ".tmt"
_GITDIR_PREFIX = "gitdir:"


def _git_common_dir(root: Path) -> Path | None:
    """The repository's common git directory, resolved without running git.

    ``tmt context`` reads this store on every session start, so the
    location must not depend on git being on PATH or on a subprocess.

    Only the registry root is inspected, deliberately. Walking upward the
    way git does would follow a stray ancestor ``.git`` — a dotfiles
    repository at ``$HOME``, or a ``git init`` someone left in ``/tmp`` —
    and write this repository's notes into an unrelated repository's git
    directory. A registry in a subdirectory of a repository therefore
    falls back to a local store, which ``_ensure_ignored`` keeps
    uncommittable.
    """
    return _git_dir_at(root)


def _git_dir_at(directory: Path) -> Path | None:
    marker = directory / ".git"
    if marker.is_dir():
        return marker
    if not marker.is_file():
        return None
    try:
        text = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    pointer = text.strip()
    if not pointer.startswith(_GITDIR_PREFIX):
        return None
    gitdir = Path(pointer[len(_GITDIR_PREFIX):].strip())
    if not gitdir.is_absolute():
        gitdir = directory / gitdir
    common = gitdir / "commondir"
    if common.is_file():
        try:
            relative = common.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return gitdir
        if relative:
            resolved = Path(relative)
            return (
                resolved if resolved.is_absolute() else gitdir / resolved
            )
    return gitdir


def state_dir(root: Path) -> Path:
    """Where this repository's untracked tmt state lives."""
    common = _git_common_dir(root)
    if common is not None:
        return common / STATE_DIRNAME
    return root / FALLBACK_DIRNAME


def store_path(root: Path) -> Path:
    return state_dir(root) / NOTES_FILENAME


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


def _ensure_ignored(directory: Path) -> None:
    """Keep the fallback store out of a repository created around it."""
    if directory.name != FALLBACK_DIRNAME:
        return
    marker = directory / ".gitignore"
    if marker.is_symlink() or marker.exists():
        return
    try:
        marker.write_text("*\n", encoding="utf-8")
    except OSError:
        pass


def append(root: Path, slug: str, note_text: str | None) -> int:
    """Record one note; return the slug's new count."""
    directory = state_dir(root)
    paths.make_directory(directory)
    _ensure_ignored(directory)
    line = json.dumps(
        {"note": note_text, "slug": slug},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    path = directory / NOTES_FILENAME
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


def slug_count(root: Path, slug: str) -> int:
    return sum(1 for record in _read(root) if record["slug"] == slug)


def dismiss(root: Path, slug: str) -> int:
    """Drop every note for ``slug``; return how many were removed."""
    records = _read(root)
    kept = [record for record in records if record["slug"] != slug]
    removed = len(records) - len(kept)
    if not removed:
        return 0
    lines = [
        json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        for record in kept
    ]
    text = "".join(line + "\n" for line in lines)
    paths.write_atomic(store_path(root), text)
    return removed

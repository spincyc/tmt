"""Containment and durable writes for every path tmt writes.

tmt only ever writes inside the repository it was pointed at. A symlink
is not a licence to leave: ``tools``, ``tmt.json``, and ``AGENTS.md`` are
resolved before use, and a target outside the root is refused rather than
followed. Registry-sized writes are staged and renamed so a kill never
leaves a truncated committed file.
"""

from __future__ import annotations

import os
from pathlib import Path

from tmt.registry import TmtError

DEFAULT_FILE_MODE = 0o644
EXECUTABLE_FILE_MODE = 0o755


def resolve_within(root: Path, path: Path, *, label: str) -> Path:
    """Return ``path`` resolved, refusing anything outside ``root``."""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError as error:
        raise TmtError("io-error", f"{label} {path}: {error}") from error
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise TmtError(
            "containment",
            f"{label} {path} resolves to {resolved}, outside the repository "
            f"{root_resolved}; tmt refuses to follow it",
        )
    return resolved


def refuse_existing(path: Path, *, label: str = "") -> None:
    """Raise ``already-exists`` for any existing path, symlinks included."""
    if path.is_symlink() or path.exists():
        raise TmtError("already-exists", f"{label or path} already exists")


def make_directory(path: Path) -> None:
    """Create ``path`` and its parents, reporting a usable error."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error


def unlink(path: Path) -> None:
    """Delete ``path``, reporting a usable error."""
    try:
        path.unlink()
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error


def rename(source: Path, target: Path) -> None:
    """Move ``source`` to ``target`` without crossing onto an existing file."""
    try:
        os.rename(source, target)
    except OSError as error:
        raise TmtError("io-error", f"{source} -> {target}: {error}") from error


def write_new(path: Path, text: str, *, mode: int = DEFAULT_FILE_MODE) -> None:
    """Create ``path`` exclusively; never write through an existing link."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError:
        raise TmtError("already-exists", f"{path} already exists") from None
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error
    os.chmod(path, mode)


def write_atomic(
    path: Path, text: str, *, mode: int | None = None
) -> None:
    """Replace ``path`` through a staged sibling and one rename.

    A symlinked ``path`` is followed to its target so the link survives;
    an existing file keeps its mode unless ``mode`` overrides it.
    """
    target = Path(os.path.realpath(path))
    try:
        existing_mode = target.stat().st_mode & 0o777
    except OSError:
        existing_mode = None
    final_mode = mode if mode is not None else existing_mode
    if final_mode is None:
        final_mode = DEFAULT_FILE_MODE
    staged = target.with_name(f".{target.name}.{os.getpid()}.tmt-tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(staged, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(staged, final_mode)
            os.replace(staged, target)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error

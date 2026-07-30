"""Containment, durable writes, and serialization for tmt's own writes.

tmt only ever writes inside the repository it was pointed at. A symlink
is not a licence to leave: ``tools``, ``tmt.json``, and ``AGENTS.md`` are
resolved before use, and a target outside the root is refused rather than
followed. Registry-sized writes are staged and renamed so a kill never
leaves a truncated committed file.

Atomicity is not enough on its own. Every tmt mutation reads a file,
changes it, and writes it back, so two concurrent processes can each
read the same state and the second write silently drop the first one's
work. ``locked`` serializes a whole read-modify-write per repository;
read-only commands never take it.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from tmt.registry import TmtError

DEFAULT_FILE_MODE = 0o644
EXECUTABLE_FILE_MODE = 0o755
STATE_DIRNAME = "tmt"
FALLBACK_DIRNAME = ".tmt"
LOCK_FILENAME = "lock"
LOCK_TIMEOUT_SECONDS = 5.0

_GITDIR_PREFIX = "gitdir:"
_POLL_SECONDS = 0.02
# flock belongs to an open file description, so a second acquisition from
# this same process would wait on itself; count the nesting instead.
_depth: dict[str, int] = {}


def resolve_within(root: Path, path: Path, *, label: str) -> Path:
    """Return ``path`` resolved, refusing anything outside ``root``.

    Containment is decided at resolve time. The writers that follow guard
    only the final component (``O_NOFOLLOW``), so someone who can already
    write inside the repository can swap a parent directory for a symlink
    between this call and the write and escape. Defending that needs
    ``openat`` walking; tmt does not attempt it.
    """
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
            # On the descriptor, not the path: chmod after the close would
            # be a window to unlink and substitute a symlink.
            os.fchmod(handle.fileno(), mode)
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error


def _fsync_directory(directory: Path) -> None:
    """Make a completed rename durable, where the filesystem allows it."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


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
    try:
        # A unique staging name: a name derived from the pid outlives a
        # kill and then blocks every later run that draws the same pid.
        descriptor, staged_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmt-tmp",
        )
        staged = Path(staged_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fchmod(handle.fileno(), final_mode)
                os.fsync(handle.fileno())
            os.replace(staged, target)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error
    _fsync_directory(target.parent)


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
    """Where this repository's untracked machine-local tmt state lives.

    The git common directory is resolved without running git: ``tmt
    context`` reads this store on every session start, so the location
    must not depend on git being on PATH or on a subprocess.

    Only the registry root is inspected, deliberately. Walking upward the
    way git does would follow a stray ancestor ``.git`` — a dotfiles
    repository at ``$HOME``, or a ``git init`` someone left in ``/tmp`` —
    and write this repository's state into an unrelated repository's git
    directory. A registry in a subdirectory of a repository therefore
    falls back to a local store, which ``_ensure_ignored`` keeps
    uncommittable.
    """
    common = _git_dir_at(root)
    if common is not None:
        return common / STATE_DIRNAME
    return root / FALLBACK_DIRNAME


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


def _flock_within(descriptor: int, path: Path) -> None:
    """Take the lock, or give up: flock itself has no timeout to pass."""
    limit = LOCK_TIMEOUT_SECONDS
    deadline = time.monotonic() + limit
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise TmtError("io-error", f"{path}: {error}") from error
        if time.monotonic() >= deadline:
            raise TmtError(
                "io-error",
                f"another tmt process holds {path}; gave up waiting "
                f"after {limit:g}s. Retry once it finishes.",
            )
        time.sleep(_POLL_SECONDS)


@contextlib.contextmanager
def locked(root: Path) -> Iterator[None]:
    """Hold this repository's mutation lock for the whole block.

    One lock per repository, not per file: the mutations are short, and a
    single lock cannot be taken in two orders and deadlock. It lives in
    the untracked state directory so no work tree gains a file to commit,
    and it is an ``flock``, which the kernel releases when the holder
    dies — a lock whose mere existence meant "locked" would wedge every
    later run after one kill.
    """
    directory = state_dir(root)
    make_directory(directory)
    _ensure_ignored(directory)
    path = directory / LOCK_FILENAME
    key = os.fspath(path)
    if _depth.get(key):
        _depth[key] += 1
        try:
            yield
        finally:
            _depth[key] -= 1
        return
    try:
        descriptor = os.open(
            path, os.O_RDWR | os.O_CREAT, DEFAULT_FILE_MODE
        )
    except OSError as error:
        raise TmtError("io-error", f"{path}: {error}") from error
    try:
        _flock_within(descriptor, path)
        _depth[key] = 1
        try:
            yield
        finally:
            _depth.pop(key, None)
    finally:
        # The close is the release; nothing unlinks the lock file, so a
        # concurrent waiter keeps waiting on the same inode.
        os.close(descriptor)

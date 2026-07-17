"""Serialize local Curator mutation entry points with an OS file lock."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
from collections.abc import Iterator


class ProjectLockedError(RuntimeError):
    """Report that another Curator process owns the project write lock."""


_HELD_LOCKS: dict[Path, tuple[object, int]] = {}


@contextmanager
def project_write_lock(project_root: Path | str) -> Iterator[None]:
    """Hold a re-entrant non-blocking project lock until the mutation completes."""
    root = Path(project_root)
    lock_path = root / ".curator" / "runtime.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = lock_path.resolve()
    held = _HELD_LOCKS.get(resolved)
    if held is not None:
        handle, depth = held
        _HELD_LOCKS[resolved] = (handle, depth + 1)
        try:
            yield
        finally:
            _HELD_LOCKS[resolved] = (handle, depth)
        return

    handle = resolved.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProjectLockedError(
                "Another Curator is running this project (read-only mode)."
            ) from error
        _HELD_LOCKS[resolved] = (handle, 1)
        try:
            yield
        finally:
            _HELD_LOCKS.pop(resolved, None)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()

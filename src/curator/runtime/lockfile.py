"""Serialize local Curator mutation entry points with an OS file lock."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
from collections.abc import Iterator
import threading


class ProjectLockedError(RuntimeError):
    """Report that another Curator process owns the project write lock."""


_HELD_LOCKS: dict[Path, tuple[object, int, int]] = {}
_HELD_LOCKS_GUARD = threading.RLock()


@contextmanager
def project_write_lock(project_root: Path | str) -> Iterator[None]:
    """Hold a re-entrant non-blocking project lock until the mutation completes."""
    root = Path(project_root)
    lock_path = root / ".curator" / "runtime.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = lock_path.resolve()
    owner = threading.get_ident()
    with _HELD_LOCKS_GUARD:
        held = _HELD_LOCKS.get(resolved)
        if held is not None:
            handle, depth, held_owner = held
            if held_owner != owner:
                raise ProjectLockedError(
                    "Another Curator worker owns this project (read-only mode)."
                )
            _HELD_LOCKS[resolved] = (handle, depth + 1, owner)
            reentrant = True
        else:
            handle = resolved.open("a+")
            reentrant = False
    if reentrant:
        try:
            yield
        finally:
            with _HELD_LOCKS_GUARD:
                current = _HELD_LOCKS.get(resolved)
                if current is not None:
                    current_handle, current_depth, current_owner = current
                    _HELD_LOCKS[resolved] = (
                        current_handle,
                        max(1, current_depth - 1),
                        current_owner,
                    )
        return

    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProjectLockedError(
                "Another Curator is running this project (read-only mode)."
            ) from error
        with _HELD_LOCKS_GUARD:
            _HELD_LOCKS[resolved] = (handle, 1, owner)
        try:
            yield
        finally:
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.pop(resolved, None)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()

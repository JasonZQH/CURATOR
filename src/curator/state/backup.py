"""Copy the Curator ledger aside before a schema migration rewrites it."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Migration backups and reset archives are both "a ledger as it was", so they share one
# directory and one timestamp format. The suffix is what tells them apart on disk.
_ARCHIVE_DIR_NAME = "archive"
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
PRE_MIGRATION_SUFFIX = "-pre-migration"


def ledger_archive_dir(curator_dir: Path) -> Path:
    """Return the directory holding superseded copies of the ledger."""
    return Path(curator_dir) / _ARCHIVE_DIR_NAME


def archive_stamp(now: datetime | None = None) -> str:
    """Return the UTC timestamp used to name an archived ledger."""
    return (now or datetime.now(UTC)).strftime(_STAMP_FORMAT)


def backup_ledger(
    connection: sqlite3.Connection,
    curator_dir: Path,
    now: datetime | None = None,
) -> Path:
    """Copy the open ledger into the archive directory and return the backup path.

    Uses SQLite's online backup API rather than copying the file. The ledger runs in WAL
    mode, so a file copy can miss pages still sitting in the write-ahead log and produce a
    backup that is silently short of the data it is supposed to preserve.
    """
    directory = ledger_archive_dir(curator_dir)
    directory.mkdir(parents=True, exist_ok=True)

    destination_path = _free_backup_path(directory, archive_stamp(now))
    destination = sqlite3.connect(destination_path)
    try:
        connection.backup(destination)
    finally:
        destination.close()
    return destination_path


def latest_pre_migration_backup(curator_dir: Path) -> Path | None:
    """Return the newest pre-migration backup, or None when none has been taken.

    Reads the directory rather than the ledger, so it still answers when the ledger itself
    will not open — which is exactly when someone is looking for a backup.
    """
    directory = ledger_archive_dir(curator_dir)
    if not directory.is_dir():
        return None

    backups = list(directory.glob(f"curator-*{PRE_MIGRATION_SUFFIX}.sqlite"))
    if not backups:
        return None
    # By mtime, not by name: a same-second backup is disambiguated with an index that
    # sorts before the plain name, so lexicographic order would report the oldest.
    return max(backups, key=lambda path: path.stat().st_mtime)


def _free_backup_path(directory: Path, stamp: str) -> Path:
    """Return a backup path that does not already exist.

    Two migrations inside the same second would otherwise resolve to one filename and the
    second would overwrite the first — discarding the older ledger state.
    """
    candidate = directory / f"curator-{stamp}{PRE_MIGRATION_SUFFIX}.sqlite"
    if not candidate.exists():
        return candidate

    for index in range(2, 100):
        candidate = directory / f"curator-{stamp}-{index}{PRE_MIGRATION_SUFFIX}.sqlite"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"cannot find a free backup name in {directory}")

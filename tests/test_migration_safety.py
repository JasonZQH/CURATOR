"""Verify a schema migration backs the ledger up, is atomic, and stays visible.

Every command that opens the ledger runs migrations, so the guarantees under test are:
the old ledger is preserved before anything writes, a failure leaves the ledger exactly as
it was, and nothing migrates without a way to see it coming.
"""

import sqlite3

import pytest

from curator.core.errors import CuratorStateError
from curator.core.paths import build_curator_paths
from curator.diagnostics.doctor import inspect_project_health
from curator.state.backup import (
    backup_ledger,
    latest_pre_migration_backup,
    ledger_archive_dir,
)
from curator.state.db import (
    connect_database,
    initialize_database,
    pending_migrations,
)


def _open(tmp_path):
    """Return a connection to this project's ledger."""
    return connect_database(build_curator_paths(tmp_path).database)


def _backups(tmp_path):
    """Return every pre-migration backup on disk for this project."""
    directory = ledger_archive_dir(build_curator_paths(tmp_path).curator_dir)
    return sorted(directory.glob("*-pre-migration.sqlite")) if directory.is_dir() else []


def _schema_rows(connection):
    """Return the schema_version table as comparable tuples."""
    return [
        (row["version"], row["applied_at"])
        for row in connection.execute("select version, applied_at from schema_version")
    ]


def _shipped_versions() -> tuple[int, ...]:
    """Return the migration versions this build actually ships."""
    from curator.state.db import VERSIONED_MIGRATIONS

    return tuple(version for version, _ in VERSIONED_MIGRATIONS)


def _add_migration(monkeypatch, migration) -> int:
    """Append one migration after the shipped ones and return its version.

    The version is derived rather than written down so these tests keep testing the
    mechanism instead of colliding with the next real migration to land.
    """
    from curator.state import db

    version = max(_shipped_versions()) + 1
    monkeypatch.setattr(
        db, "VERSIONED_MIGRATIONS", (*db.VERSIONED_MIGRATIONS, (version, migration))
    )
    return version


def test_a_fresh_ledger_is_not_backed_up(tmp_path):
    """Verify creating a ledger writes no backup — there is nothing to preserve."""
    connection = _open(tmp_path)

    outcome = initialize_database(connection)

    assert outcome is not None and outcome.applied == _shipped_versions()
    assert outcome.backup is None
    assert _backups(tmp_path) == []
    connection.close()


def test_an_up_to_date_ledger_reports_nothing_and_writes_no_backup(tmp_path):
    """Verify the common case — every command opens the ledger — stays free of copies."""
    connection = _open(tmp_path)
    initialize_database(connection)

    for _ in range(10):
        assert initialize_database(connection) is None

    assert _backups(tmp_path) == []
    connection.close()


def test_a_pending_migration_backs_the_ledger_up_first(tmp_path, monkeypatch):
    """Verify an existing ledger is copied aside before a new migration touches it."""
    connection = _open(tmp_path)
    initialize_database(connection)
    added = _add_migration(
        monkeypatch,
        lambda conn: conn.execute("alter table memory_entries add column probe text"),
    )

    outcome = initialize_database(connection)

    assert outcome is not None and outcome.applied == (added,)
    assert outcome.from_version == added - 1 and outcome.to_version == added
    assert outcome.backup is not None and outcome.backup.exists()
    assert _backups(tmp_path) == [outcome.backup]

    # The backup is a real ledger, and it predates the migration.
    restored = sqlite3.connect(outcome.backup)
    columns = {row[1] for row in restored.execute("pragma table_info(memory_entries)")}
    assert "probe" not in columns
    restored.close()
    connection.close()


def test_a_failed_migration_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    """Verify a migration that raises rolls back its DDL and its schema_version row."""
    connection = _open(tmp_path)
    initialize_database(connection)
    before_schema = _schema_rows(connection)
    before_columns = {row["name"] for row in connection.execute("pragma table_info(memory_entries)")}

    def _doomed(conn):
        """Change the schema, then fail — the change must not survive."""
        conn.execute("alter table memory_entries add column half_applied text")
        raise RuntimeError("migration exploded")

    _add_migration(monkeypatch, _doomed)

    with pytest.raises(CuratorStateError):
        initialize_database(connection)

    assert _schema_rows(connection) == before_schema  # version 3 was never recorded
    after_columns = {row["name"] for row in connection.execute("pragma table_info(memory_entries)")}
    assert after_columns == before_columns  # the DDL rolled back with it

    backups = _backups(tmp_path)
    assert len(backups) == 1  # and the pre-migration copy is still there to fall back on
    sqlite3.connect(backups[0]).close()
    connection.close()


def test_the_backup_captures_data_still_sitting_in_the_wal(tmp_path):
    """Verify the online backup API is used, not a file copy.

    The ledger runs in WAL mode, so a committed row can live in the -wal file until a
    checkpoint. Copying curator.sqlite alone would silently lose it.
    """
    connection = _open(tmp_path)
    initialize_database(connection)
    connection.execute("create table wal_probe (value text)")
    connection.execute("insert into wal_probe values ('kept')")
    connection.commit()

    wal = build_curator_paths(tmp_path).database.with_name("curator.sqlite-wal")
    assert wal.exists() and wal.stat().st_size > 0  # the row really is in the WAL

    backup = backup_ledger(connection, build_curator_paths(tmp_path).curator_dir)

    restored = sqlite3.connect(backup)
    assert [row[0] for row in restored.execute("select value from wal_probe")] == ["kept"]
    restored.close()
    connection.close()


def test_pending_migrations_treats_a_ledger_without_schema_version_as_unmigrated(tmp_path):
    """Verify a ledger predating the schema_version table is migratable, not an error."""
    connection = _open(tmp_path)

    assert pending_migrations(connection) == list(_shipped_versions())  # no schema_version table yet
    connection.close()


def test_doctor_reports_pending_migrations_without_applying_them(tmp_path, monkeypatch):
    """Verify the dry-run really is dry — doctor must never migrate the ledger."""
    connection = _open(tmp_path)
    initialize_database(connection)
    before = _schema_rows(connection)
    connection.close()

    added = _add_migration(monkeypatch, lambda conn: conn.execute("select 1"))

    report = inspect_project_health(tmp_path)
    inspect_project_health(tmp_path)

    assert report.checks["migrations"].status == "pending"
    assert str(added) in report.checks["migrations"].detail

    connection = _open(tmp_path)
    assert _schema_rows(connection) == before
    assert pending_migrations(connection) == [added]
    connection.close()


def test_doctor_points_at_the_newest_backup_with_a_restore_command(tmp_path, monkeypatch):
    """Verify recovery never requires remembering a timestamp."""
    connection = _open(tmp_path)
    initialize_database(connection)
    _add_migration(monkeypatch, lambda conn: conn.execute("select 1"))
    outcome = initialize_database(connection)
    connection.close()

    check = inspect_project_health(tmp_path).checks["backup"]

    assert check.status == "ok"
    assert str(outcome.backup) in check.detail
    assert "cp " in check.detail and "curator.sqlite" in check.detail


def test_a_failed_backup_is_never_offered_as_a_restore_point(tmp_path, monkeypatch):
    """Verify a backup that dies half way cannot become what doctor tells you to restore.

    sqlite3.connect creates the destination up front, so a failure mid-copy used to leave a
    truncated file carrying the real name. Being newest, it shadowed every good backup — and
    the restore command copies it over the live ledger, destroying it.
    """
    from curator.state.db import CuratorConnection

    curator_dir = build_curator_paths(tmp_path).curator_dir
    connection = _open(tmp_path)
    initialize_database(connection)
    good = backup_ledger(connection, curator_dir)

    def _explode(self, target, **kwargs):
        """Fail the way a full disk does — after the destination file already exists."""
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(CuratorConnection, "backup", _explode, raising=False)
    with pytest.raises(sqlite3.OperationalError):
        backup_ledger(connection, curator_dir)
    monkeypatch.undo()

    assert _backups(tmp_path) == [good]  # the failed attempt left nothing behind
    assert latest_pre_migration_backup(curator_dir) == good
    assert not list(ledger_archive_dir(curator_dir).glob("*.partial"))
    connection.close()


def test_an_empty_backup_file_is_not_offered_as_a_restore_point(tmp_path):
    """Verify a zero-byte file in the archive never becomes the advertised restore point."""
    curator_dir = build_curator_paths(tmp_path).curator_dir
    connection = _open(tmp_path)
    initialize_database(connection)
    good = backup_ledger(connection, curator_dir)

    stray = ledger_archive_dir(curator_dir) / "curator-29990101T000000Z-pre-migration.sqlite"
    stray.touch()  # newer by name and mtime, but empty

    assert latest_pre_migration_backup(curator_dir) == good
    connection.close()


def test_latest_backup_is_the_newest_one_not_the_last_alphabetically(tmp_path):
    """Verify same-second backups do not make an older copy look like the newest."""
    curator_dir = build_curator_paths(tmp_path).curator_dir
    connection = _open(tmp_path)
    initialize_database(connection)

    first = backup_ledger(connection, curator_dir)
    second = backup_ledger(connection, curator_dir)  # same second -> indexed name

    assert first != second
    assert latest_pre_migration_backup(curator_dir) == second
    connection.close()

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


def _add_migration(monkeypatch, version, migration):
    """Append one migration to the registry for the duration of a test."""
    from curator.state import db

    monkeypatch.setattr(
        db, "VERSIONED_MIGRATIONS", (*db.VERSIONED_MIGRATIONS, (version, migration))
    )


def test_a_fresh_ledger_is_not_backed_up(tmp_path):
    """Verify creating a ledger writes no backup — there is nothing to preserve."""
    connection = _open(tmp_path)

    outcome = initialize_database(connection)

    assert outcome is not None and outcome.applied == (1, 2)
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
    _add_migration(
        monkeypatch,
        3,
        lambda conn: conn.execute("alter table memory_entries add column probe text"),
    )

    outcome = initialize_database(connection)

    assert outcome is not None and outcome.applied == (3,)
    assert outcome.from_version == 2 and outcome.to_version == 3
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

    _add_migration(monkeypatch, 3, _doomed)

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

    assert pending_migrations(connection) == [1, 2]  # no schema_version table exists yet
    connection.close()


def test_doctor_reports_pending_migrations_without_applying_them(tmp_path, monkeypatch):
    """Verify the dry-run really is dry — doctor must never migrate the ledger."""
    connection = _open(tmp_path)
    initialize_database(connection)
    before = _schema_rows(connection)
    connection.close()

    _add_migration(monkeypatch, 3, lambda conn: conn.execute("select 1"))

    report = inspect_project_health(tmp_path)
    inspect_project_health(tmp_path)

    assert report.checks["migrations"].status == "pending"
    assert "3" in report.checks["migrations"].detail

    connection = _open(tmp_path)
    assert _schema_rows(connection) == before
    assert pending_migrations(connection) == [3]
    connection.close()


def test_doctor_points_at_the_newest_backup_with_a_restore_command(tmp_path, monkeypatch):
    """Verify recovery never requires remembering a timestamp."""
    connection = _open(tmp_path)
    initialize_database(connection)
    _add_migration(monkeypatch, 3, lambda conn: conn.execute("select 1"))
    outcome = initialize_database(connection)
    connection.close()

    check = inspect_project_health(tmp_path).checks["backup"]

    assert check.status == "ok"
    assert str(outcome.backup) in check.detail
    assert "cp " in check.detail and "curator.sqlite" in check.detail


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

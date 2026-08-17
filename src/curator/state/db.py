"""Manage SQLite connections and database initialization."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from curator.core.errors import CuratorStateError
from curator.state.backup import backup_ledger
from curator.state.migrations import phase0_schema_sql


@dataclass(frozen=True)
class MigrationOutcome:
    """Describe the schema migrations one initialization actually applied."""

    applied: tuple[int, ...]
    from_version: int
    to_version: int
    backup: Path | None = None


class CuratorConnection(sqlite3.Connection):
    """Track Curator-owned transaction nesting without mutating sqlite3.Connection."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize one connection with an empty transaction stack."""
        super().__init__(*args, **kwargs)
        self.txn_depth = 0
        self._savepoints: list[str] = []
        self._savepoint_counter = 0

    def begin_transaction(self) -> None:
        """Begin an immediate transaction or a nested SAVEPOINT."""
        if self.txn_depth == 0:
            self.execute("BEGIN IMMEDIATE")
        else:
            self._savepoint_counter += 1
            name = f"curator_sp_{self._savepoint_counter}"
            self._savepoints.append(name)
            self.execute(f"SAVEPOINT {name}")
        self.txn_depth += 1

    def commit_transaction(self) -> None:
        """Commit the current transaction level and release nested SAVEPOINTs."""
        if self.txn_depth <= 0:
            return
        if self.txn_depth == 1:
            self.commit()
        else:
            self.execute(f"RELEASE SAVEPOINT {self._savepoints.pop()}")
        self.txn_depth -= 1

    def rollback_transaction(self) -> None:
        """Roll back the current transaction level and discard nested SAVEPOINTs."""
        if self.txn_depth <= 0:
            return
        if self.txn_depth == 1:
            self.rollback()
        else:
            name = self._savepoints.pop()
            self.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.execute(f"RELEASE SAVEPOINT {name}")
        self.txn_depth -= 1


def connect_database(path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with row dictionaries enabled."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path, factory=CuratorConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    connection.execute("pragma journal_mode = wal")
    return connection


def _ensure_provider_run_identity_columns(connection: sqlite3.Connection) -> None:
    """Add provider identity columns to legacy provider run ledgers."""
    columns = {
        row["name"]
        for row in connection.execute("pragma table_info(provider_runs)").fetchall()
    }
    if "provider_profile_id" not in columns:
        connection.execute("alter table provider_runs add column provider_profile_id text")
    if "provider_session_id" not in columns:
        connection.execute("alter table provider_runs add column provider_session_id text")


def _ensure_memory_entry_learning_columns(connection: sqlite3.Connection) -> None:
    """Add learning metadata columns to legacy memory entry ledgers."""
    columns = {
        row["name"]
        for row in connection.execute("pragma table_info(memory_entries)").fetchall()
    }
    if "kind" not in columns:
        connection.execute(
            "alter table memory_entries add column kind text not null default 'note'"
        )
    if "updated_at" not in columns:
        connection.execute("alter table memory_entries add column updated_at text")


def _ensure_event_causation_column(connection: sqlite3.Connection) -> None:
    """Add the event causation link to ledgers created before it existed."""
    columns = {
        row["name"] for row in connection.execute("pragma table_info(events)").fetchall()
    }
    if "causation_id" not in columns:
        connection.execute("alter table events add column causation_id text")


VERSIONED_MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = (
    (1, _ensure_provider_run_identity_columns),
    (2, _ensure_memory_entry_learning_columns),
    (3, _ensure_event_causation_column),
)


def applied_migrations(connection: sqlite3.Connection) -> set[int]:
    """Return the migration versions this ledger has already recorded.

    A ledger old enough to predate the schema_version table has recorded nothing, which is
    a valid state to migrate from rather than an error — and this is called from read-only
    callers like doctor that never create the table.
    """
    try:
        rows = connection.execute("select version from schema_version").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row["version"] for row in rows}


def pending_migrations(connection: sqlite3.Connection) -> list[int]:
    """Return the migration versions this ledger has not applied yet, in order."""
    already = applied_migrations(connection)
    return [version for version, _ in VERSIONED_MIGRATIONS if version not in already]


def _apply_versioned_migrations(connection: sqlite3.Connection, pending: list[int]) -> None:
    """Apply pending migrations as one all-or-nothing unit.

    Every migration and its schema_version row share a single transaction: SQLite rolls
    DDL back with everything else, so a failure half way through leaves the ledger exactly
    as it was rather than in a state no version of Curator is written to read.
    """
    migrations = dict(VERSIONED_MIGRATIONS)
    connection.begin_transaction()
    try:
        for version in pending:
            migrations[version](connection)
            connection.execute(
                "insert into schema_version (version, applied_at) values (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
        connection.commit_transaction()
    except Exception as error:
        connection.rollback_transaction()
        raise CuratorStateError(f"schema migration failed and was rolled back: {error}") from error


def _ledger_database_path(connection: sqlite3.Connection) -> Path | None:
    """Return the file backing this connection, or None for an in-memory ledger."""
    for row in connection.execute("pragma database_list").fetchall():
        if row["name"] == "main" and row["file"]:
            return Path(row["file"])
    return None


def _ledger_has_content(connection: sqlite3.Connection) -> bool:
    """Report whether this ledger already holds objects worth preserving."""
    row = connection.execute("select count(*) as count from sqlite_master").fetchone()
    return bool(row["count"])


def initialize_database(connection: sqlite3.Connection) -> MigrationOutcome | None:
    """Create the Phase 0 SQLite tables and apply pending migrations.

    Returns what was migrated, or None when the ledger was already current — which is the
    common case, since every command that opens the ledger lands here. An existing ledger
    with work to do is copied to .curator/archive/ first, before anything writes to it.
    """
    pending = pending_migrations(connection)
    previous = max(applied_migrations(connection), default=0)

    backup: Path | None = None
    if pending and _ledger_has_content(connection):
        database_path = _ledger_database_path(connection)
        if database_path is not None:
            backup = backup_ledger(connection, database_path.parent)

    connection.executescript(phase0_schema_sql())
    if pending:
        _apply_versioned_migrations(connection, pending)
    connection.commit()

    if not pending:
        return None
    return MigrationOutcome(
        applied=tuple(pending),
        from_version=previous,
        to_version=max(pending),
        backup=backup,
    )

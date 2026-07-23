"""Manage SQLite connections and database initialization."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from curator.state.migrations import phase0_schema_sql


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


VERSIONED_MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = (
    (1, _ensure_provider_run_identity_columns),
    (2, _ensure_memory_entry_learning_columns),
)


def _apply_versioned_migrations(connection: sqlite3.Connection) -> None:
    """Run numbered migrations that are not yet recorded in schema_version."""
    applied = {
        row["version"]
        for row in connection.execute("select version from schema_version").fetchall()
    }
    for version, migration in VERSIONED_MIGRATIONS:
        if version in applied:
            continue

        migration(connection)
        connection.execute(
            "insert into schema_version (version, applied_at) values (?, ?)",
            (version, datetime.now(UTC).isoformat()),
        )


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the Phase 0 SQLite tables and apply pending migrations."""
    connection.executescript(phase0_schema_sql())
    _apply_versioned_migrations(connection)
    connection.commit()

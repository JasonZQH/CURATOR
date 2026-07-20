"""Verify Curator connection transactions and repository commit compatibility."""

import pytest

from datetime import UTC, datetime
from curator.core.enums import SessionMode
from curator.core.schema import SessionRecord
from curator.state.db import CuratorConnection, connect_database, initialize_database
from curator.state.repositories import insert_session
from curator.state.transaction import transaction


def test_nested_transaction_uses_savepoint_and_rolls_back_inner_work(tmp_path):
    """Verify nested rollback preserves the outer transaction."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    assert isinstance(connection, CuratorConnection)
    with transaction(connection):
        connection.execute("insert into schema_version values (99, 'outer')")
        with pytest.raises(RuntimeError):
            with transaction(connection):
                connection.execute("insert into schema_version values (100, 'inner')")
                raise RuntimeError("rollback inner")
    rows = connection.execute("select version from schema_version where version >= 99").fetchall()
    assert [row[0] for row in rows] == [99]
    connection.close()


def test_external_sqlite_connection_keeps_legacy_commit_behavior(tmp_path):
    """Verify repository helpers still commit a standard sqlite connection."""
    path = tmp_path / ".curator" / "legacy.sqlite"
    connection = connect_database(path)
    connection.execute(
        "create table sessions (id text primary key, project_root text, mode text, "
        "status text, created_at text, updated_at text, metadata_json text)"
    )
    insert_session(
        connection,
        SessionRecord(
            id="session-legacy",
            project_root=tmp_path,
            mode=SessionMode.AUTO,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )
    connection.close()
    reopened = connect_database(path)
    assert reopened.execute("select id from sessions").fetchone()[0] == "session-legacy"
    reopened.close()

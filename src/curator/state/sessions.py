"""Persist and load Curator session records."""

import sqlite3
from typing import Any

from curator.core.schema import SessionRecord
from curator.state._mapping import fetch_one, json_dumps, json_loads


def insert_session(connection: sqlite3.Connection, session: SessionRecord) -> None:
    """Insert or replace one session record."""
    connection.execute(
        """
        insert or replace into sessions (
            id, project_root, mode, status, created_at, updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.id,
            str(session.project_root),
            session.mode.value,
            session.status,
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
            json_dumps(session.metadata),
        ),
    )
    connection.commit()


def _map_session(row: sqlite3.Row) -> dict[str, Any]:
    """Map a sessions row into SessionRecord keyword arguments."""
    return {
        "id": row["id"],
        "project_root": row["project_root"],
        "mode": row["mode"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_session(connection: sqlite3.Connection, session_id: str) -> SessionRecord | None:
    """Load one session by id."""
    return fetch_one(
        connection,
        "select * from sessions where id = ?",
        (session_id,),
        SessionRecord,
        _map_session,
    )


def load_latest_session(connection: sqlite3.Connection) -> SessionRecord | None:
    """Load the most recently updated session."""
    return fetch_one(
        connection,
        "select * from sessions order by updated_at desc, id desc limit 1",
        (),
        SessionRecord,
        _map_session,
    )

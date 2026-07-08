"""Persist and load Curator event records."""

import sqlite3
from typing import Any

from agentctl.core.schema import EventRecord
from agentctl.state._mapping import fetch_many, json_dumps, json_loads


def insert_event(connection: sqlite3.Connection, event: EventRecord) -> None:
    """Insert or replace one event record."""
    connection.execute(
        """
        insert or replace into events (
            id, session_id, task_id, type, created_at, payload_json
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.session_id,
            event.task_id,
            event.type.value,
            event.created_at.isoformat(),
            json_dumps(event.payload),
        ),
    )
    connection.commit()


def _map_event(row: sqlite3.Row) -> dict[str, Any]:
    """Map an events row into EventRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "type": row["type"],
        "created_at": row["created_at"],
        "payload": json_loads(row["payload_json"]),
    }


def load_events_for_session(
    connection: sqlite3.Connection, session_id: str
) -> list[EventRecord]:
    """Load events for a session in creation order."""
    return fetch_many(
        connection,
        "select * from events where session_id = ? order by created_at, id",
        (session_id,),
        EventRecord,
        _map_event,
    )

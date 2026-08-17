"""Persist and load Curator event records."""

import sqlite3
from typing import Any

from curator.core.schema import EventRecord
from curator.state._mapping import fetch_many, json_dumps, json_loads, maybe_commit


def insert_event(connection: sqlite3.Connection, event: EventRecord) -> None:
    """Insert or replace one event record."""
    connection.execute(
        """
        insert or replace into events (
            id, session_id, task_id, type, created_at, payload_json, causation_id
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.session_id,
            event.task_id,
            event.type.value,
            event.created_at.isoformat(),
            json_dumps(event.payload),
            event.causation_id,
        ),
    )
    maybe_commit(connection)


def _map_event(row: sqlite3.Row) -> dict[str, Any]:
    """Map an events row into EventRecord keyword arguments.

    causation_id is read defensively: a ledger opened between the schema script and the
    migration commit still has the old column set, and a bare row["causation_id"] would
    raise there rather than degrade.
    """
    keys = row.keys()
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "type": row["type"],
        "created_at": row["created_at"],
        "payload": json_loads(row["payload_json"]),
        "causation_id": row["causation_id"] if "causation_id" in keys else None,
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

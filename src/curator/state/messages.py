"""Persist and load Curator message records."""

import sqlite3
from typing import Any

from curator.core.schema import MessageRecord
from curator.state._mapping import fetch_many, json_dumps, json_loads


def insert_message(connection: sqlite3.Connection, message: MessageRecord) -> None:
    """Insert or replace one message record."""
    connection.execute(
        """
        insert or replace into messages (
            id, session_id, task_id, role, type, content, created_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.id,
            message.session_id,
            message.task_id,
            message.role.value,
            message.type.value,
            message.content,
            message.created_at.isoformat(),
            json_dumps(message.metadata),
        ),
    )
    connection.commit()


def _map_message(row: sqlite3.Row) -> dict[str, Any]:
    """Map a messages row into MessageRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "type": row["type"],
        "content": row["content"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_messages_for_session(
    connection: sqlite3.Connection, session_id: str
) -> list[MessageRecord]:
    """Load messages for a session in creation order."""
    return fetch_many(
        connection,
        "select * from messages where session_id = ? order by created_at, id",
        (session_id,),
        MessageRecord,
        _map_message,
    )

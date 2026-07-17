"""Persist and load Curator task records."""

import sqlite3
from typing import Any

from curator.core.schema import TaskRecord
from curator.state._mapping import fetch_many, iso_or_none, json_dumps, json_loads, maybe_commit


def insert_task(connection: sqlite3.Connection, task: TaskRecord) -> None:
    """Insert or replace one task record."""
    connection.execute(
        """
        insert or replace into tasks (
            id, session_id, role, status, title, description, created_at, updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task.id,
            task.session_id,
            task.role.value,
            task.status.value,
            task.title,
            task.description,
            iso_or_none(task.created_at),
            iso_or_none(task.updated_at),
            json_dumps(task.metadata),
        ),
    )
    maybe_commit(connection)


def _map_task(row: sqlite3.Row) -> dict[str, Any]:
    """Map a tasks row into TaskRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "status": row["status"],
        "title": row["title"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_tasks_for_session(
    connection: sqlite3.Connection, session_id: str
) -> list[TaskRecord]:
    """Load tasks for a session in creation order."""
    return fetch_many(
        connection,
        "select * from tasks where session_id = ? order by created_at, id",
        (session_id,),
        TaskRecord,
        _map_task,
    )

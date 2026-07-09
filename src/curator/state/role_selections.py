"""Persist and load Curator role selection records."""

import json
import sqlite3
from typing import Any

from curator.core.schema import RoleSelectionRecord
from curator.state._mapping import fetch_many, json_dumps, json_loads


def insert_role_selection(
    connection: sqlite3.Connection, selection: RoleSelectionRecord
) -> None:
    """Insert or replace one role selection ledger record."""
    connection.execute(
        """
        insert or replace into role_selections (
            id, session_id, loop_run_id, role_id, display_name, matched_signals_json,
            score, reason, created_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            selection.id,
            selection.session_id,
            selection.loop_run_id,
            selection.role_id,
            selection.display_name,
            json.dumps(selection.matched_signals),
            selection.score,
            selection.reason,
            selection.created_at.isoformat(),
            json_dumps(selection.metadata),
        ),
    )
    connection.commit()


def _map_role_selection(row: sqlite3.Row) -> dict[str, Any]:
    """Map a role_selections row into RoleSelectionRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "loop_run_id": row["loop_run_id"],
        "role_id": row["role_id"],
        "display_name": row["display_name"],
        "matched_signals": json.loads(row["matched_signals_json"]),
        "score": row["score"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_role_selections_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[RoleSelectionRecord]:
    """Load role selection records for a loop run in creation order."""
    return fetch_many(
        connection,
        "select * from role_selections where loop_run_id = ? order by created_at, id",
        (loop_run_id,),
        RoleSelectionRecord,
        _map_role_selection,
    )

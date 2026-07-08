"""Persist and load Curator goal ledger records."""

import sqlite3
from typing import Any

from agentctl.core.schema import GoalRevisionRecord, GoalRunRecord
from agentctl.state._mapping import fetch_one, iso_or_none, json_dumps, json_loads


def insert_goal_identity(
    connection: sqlite3.Connection,
    goal_id: str,
    source_request: str,
    summary: str,
    status: str,
    current_revision_id: str | None,
    created_at: str,
    updated_at: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert or replace one goal identity record."""
    connection.execute(
        """
        insert or replace into goals (
            id, source_request, summary, status, current_revision_id, created_at,
            updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            goal_id,
            source_request,
            summary,
            status,
            current_revision_id,
            created_at,
            updated_at,
            json_dumps(metadata or {}),
        ),
    )
    connection.commit()


def insert_goal_revision(
    connection: sqlite3.Connection, revision: GoalRevisionRecord
) -> None:
    """Insert or replace one immutable accepted goal revision."""
    connection.execute(
        """
        insert or replace into goal_revisions (
            id, goal_id, revision, status, contract_json, created_at, accepted_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision.id,
            revision.goal_id,
            revision.revision,
            revision.status.value,
            json_dumps(revision.contract),
            revision.created_at.isoformat(),
            revision.accepted_at.isoformat(),
            json_dumps(revision.metadata),
        ),
    )
    connection.commit()


def insert_goal_run(connection: sqlite3.Connection, run: GoalRunRecord) -> None:
    """Insert or replace one accepted goal to loop run mapping."""
    connection.execute(
        """
        insert or replace into goal_runs (
            id, goal_id, goal_revision_id, session_id, loop_run_id, status, started_at,
            completed_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.id,
            run.goal_id,
            run.goal_revision_id,
            run.session_id,
            run.loop_run_id,
            run.status.value,
            run.started_at.isoformat(),
            iso_or_none(run.completed_at),
            json_dumps(run.metadata),
        ),
    )
    connection.commit()


def _map_goal_revision(row: sqlite3.Row) -> dict[str, Any]:
    """Map a goal_revisions row into GoalRevisionRecord keyword arguments."""
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "revision": row["revision"],
        "status": row["status"],
        "contract": json_loads(row["contract_json"]),
        "created_at": row["created_at"],
        "accepted_at": row["accepted_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_goal_run(row: sqlite3.Row) -> dict[str, Any]:
    """Map a goal_runs row into GoalRunRecord keyword arguments."""
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "goal_revision_id": row["goal_revision_id"],
        "session_id": row["session_id"],
        "loop_run_id": row["loop_run_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def next_goal_revision_number(connection: sqlite3.Connection, goal_id: str) -> int:
    """Return the next accepted revision number for a goal."""
    row = connection.execute(
        "select coalesce(max(revision), 0) + 1 as next_revision from goal_revisions where goal_id = ?",
        (goal_id,),
    ).fetchone()
    return int(row["next_revision"])


def load_goal_revision(
    connection: sqlite3.Connection, revision_id: str
) -> GoalRevisionRecord | None:
    """Load one accepted goal revision by id."""
    return fetch_one(
        connection,
        "select * from goal_revisions where id = ?",
        (revision_id,),
        GoalRevisionRecord,
        _map_goal_revision,
    )


def load_latest_goal_run(connection: sqlite3.Connection) -> GoalRunRecord | None:
    """Load the most recently started goal run."""
    return fetch_one(
        connection,
        "select * from goal_runs order by started_at desc, id desc limit 1",
        (),
        GoalRunRecord,
        _map_goal_run,
    )


def load_goal_run_for_loop(
    connection: sqlite3.Connection, loop_run_id: str
) -> GoalRunRecord | None:
    """Load the goal run bound to one loop run, scoped to that run."""
    return fetch_one(
        connection,
        "select * from goal_runs where loop_run_id = ? order by started_at desc limit 1",
        (loop_run_id,),
        GoalRunRecord,
        _map_goal_run,
    )


def load_goal_ids(connection: sqlite3.Connection) -> set[str]:
    """Load every goal id already recorded in the ledger."""
    rows = connection.execute(
        "select id from goals union select goal_id from goal_drafts"
    ).fetchall()
    return {row[0] for row in rows}

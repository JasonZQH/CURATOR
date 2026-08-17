"""Persist and load execution attempts and task dependency edges."""

import sqlite3
from typing import Any

from curator.core.schema import ExecutionRecord, TaskDependencyRecord
from curator.state._mapping import (
    fetch_many,
    iso_or_none,
    json_dumps,
    json_loads,
    maybe_commit,
)


def insert_execution(connection: sqlite3.Connection, execution: ExecutionRecord) -> None:
    """Insert or replace one execution attempt.

    Replace covers only the terminal fields: an attempt's identity — id, attempt number,
    parent — is written once at dispatch and never rewritten, the same shape provider_runs
    already uses for a run that starts before it finishes.
    """
    connection.execute(
        """
        insert or replace into executions (
            id, session_id, loop_run_id, task_id, iteration_id, attempt,
            parent_execution_id, status, started_at, completed_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution.id,
            execution.session_id,
            execution.loop_run_id,
            execution.task_id,
            execution.iteration_id,
            execution.attempt,
            execution.parent_execution_id,
            execution.status.value,
            execution.started_at.isoformat(),
            iso_or_none(execution.completed_at),
            json_dumps(execution.metadata),
        ),
    )
    maybe_commit(connection)


def _map_execution(row: sqlite3.Row) -> dict[str, Any]:
    """Map an executions row into ExecutionRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "loop_run_id": row["loop_run_id"],
        "task_id": row["task_id"],
        "iteration_id": row["iteration_id"],
        "attempt": row["attempt"],
        "parent_execution_id": row["parent_execution_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_executions_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[ExecutionRecord]:
    """Load every attempt in one loop run, oldest first."""
    return fetch_many(
        connection,
        "select * from executions where loop_run_id = ? order by attempt, started_at, id",
        (loop_run_id,),
        ExecutionRecord,
        _map_execution,
    )


def load_executions_for_task(
    connection: sqlite3.Connection, loop_run_id: str, task_id: str
) -> list[ExecutionRecord]:
    """Load every attempt at one task, oldest first.

    The next attempt's number and parent are read off the end of this list, so the retry
    lineage is a fold of the ledger and stays correct across a resume.
    """
    return fetch_many(
        connection,
        "select * from executions where loop_run_id = ? and task_id = ? "
        "order by attempt, started_at, id",
        (loop_run_id, task_id),
        ExecutionRecord,
        _map_execution,
    )


def insert_task_dependency(
    connection: sqlite3.Connection, dependency: TaskDependencyRecord
) -> None:
    """Insert or replace one task dependency edge."""
    connection.execute(
        """
        insert or replace into task_dependencies (
            id, session_id, task_id, depends_on_task_id, created_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            dependency.id,
            dependency.session_id,
            dependency.task_id,
            dependency.depends_on_task_id,
            dependency.created_at.isoformat(),
            json_dumps(dependency.metadata),
        ),
    )
    maybe_commit(connection)


def _map_task_dependency(row: sqlite3.Row) -> dict[str, Any]:
    """Map a task_dependencies row into TaskDependencyRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "depends_on_task_id": row["depends_on_task_id"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_task_dependencies_for_session(
    connection: sqlite3.Connection, session_id: str
) -> list[TaskDependencyRecord]:
    """Load every dependency edge declared for one session."""
    return fetch_many(
        connection,
        "select * from task_dependencies where session_id = ? order by task_id, id",
        (session_id,),
        TaskDependencyRecord,
        _map_task_dependency,
    )

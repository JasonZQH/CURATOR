"""Persist and load Curator loop ledger records."""

import sqlite3
from typing import Any

from curator.core.schema import LoopDecisionRecord, LoopIterationRecord, LoopRunRecord
from curator.state._mapping import fetch_many, fetch_one, iso_or_none, json_dumps, json_loads


def insert_loop_run(connection: sqlite3.Connection, loop_run: LoopRunRecord) -> None:
    """Insert or replace one loop run record."""
    connection.execute(
        """
        insert or replace into loop_runs (
            id, session_id, contract_id, template_id, status, created_at, updated_at,
            completed_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            loop_run.id,
            loop_run.session_id,
            loop_run.contract_id,
            loop_run.template_id,
            loop_run.status.value,
            loop_run.created_at.isoformat(),
            loop_run.updated_at.isoformat(),
            iso_or_none(loop_run.completed_at),
            json_dumps(loop_run.metadata),
        ),
    )
    connection.commit()


def insert_loop_iteration(
    connection: sqlite3.Connection, iteration: LoopIterationRecord
) -> None:
    """Insert or replace one loop iteration record."""
    connection.execute(
        """
        insert or replace into loop_iterations (
            id, loop_run_id, session_id, task_id, sequence, step_type, role, status,
            started_at, completed_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            iteration.id,
            iteration.loop_run_id,
            iteration.session_id,
            iteration.task_id,
            iteration.sequence,
            iteration.step_type.value,
            iteration.role.value,
            iteration.status.value,
            iteration.started_at.isoformat(),
            iso_or_none(iteration.completed_at),
            json_dumps(iteration.metadata),
        ),
    )
    connection.commit()


def insert_loop_decision(
    connection: sqlite3.Connection, decision: LoopDecisionRecord
) -> None:
    """Insert or replace one loop decision record."""
    connection.execute(
        """
        insert or replace into loop_decisions (
            id, loop_run_id, iteration_id, decision, stop_condition, reason, created_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.id,
            decision.loop_run_id,
            decision.iteration_id,
            decision.decision.value,
            decision.stop_condition.value if decision.stop_condition else None,
            decision.reason,
            decision.created_at.isoformat(),
            json_dumps(decision.metadata),
        ),
    )
    connection.commit()


def _map_loop_run(row: sqlite3.Row) -> dict[str, Any]:
    """Map a loop_runs row into LoopRunRecord keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "contract_id": row["contract_id"],
        "template_id": row["template_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_loop_iteration(row: sqlite3.Row) -> dict[str, Any]:
    """Map a loop_iterations row into LoopIterationRecord keyword arguments."""
    return {
        "id": row["id"],
        "loop_run_id": row["loop_run_id"],
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "sequence": row["sequence"],
        "step_type": row["step_type"],
        "role": row["role"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_loop_decision(row: sqlite3.Row) -> dict[str, Any]:
    """Map a loop_decisions row into LoopDecisionRecord keyword arguments."""
    return {
        "id": row["id"],
        "loop_run_id": row["loop_run_id"],
        "iteration_id": row["iteration_id"],
        "decision": row["decision"],
        "stop_condition": row["stop_condition"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_loop_run(connection: sqlite3.Connection, loop_run_id: str) -> LoopRunRecord | None:
    """Load one loop run by id."""
    return fetch_one(
        connection,
        "select * from loop_runs where id = ?",
        (loop_run_id,),
        LoopRunRecord,
        _map_loop_run,
    )


def load_loop_runs_for_session(
    connection: sqlite3.Connection, session_id: str
) -> list[LoopRunRecord]:
    """Load loop runs for a session in creation order."""
    return fetch_many(
        connection,
        "select * from loop_runs where session_id = ? order by created_at, id",
        (session_id,),
        LoopRunRecord,
        _map_loop_run,
    )


def load_loop_iterations(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[LoopIterationRecord]:
    """Load loop iterations for a loop run in sequence order."""
    return fetch_many(
        connection,
        "select * from loop_iterations where loop_run_id = ? order by sequence",
        (loop_run_id,),
        LoopIterationRecord,
        _map_loop_iteration,
    )


def load_loop_iterations_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[LoopIterationRecord]:
    """Load loop iterations for a loop run in sequence order."""
    return load_loop_iterations(connection, loop_run_id)


def load_loop_decisions(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[LoopDecisionRecord]:
    """Load loop decisions for a loop run in creation order."""
    return fetch_many(
        connection,
        "select * from loop_decisions where loop_run_id = ? order by created_at, id",
        (loop_run_id,),
        LoopDecisionRecord,
        _map_loop_decision,
    )


def load_loop_decisions_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[LoopDecisionRecord]:
    """Load loop decisions for a loop run in creation order."""
    return load_loop_decisions(connection, loop_run_id)

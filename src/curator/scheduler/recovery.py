"""Reconcile durable execution rows after an interrupted Curator process."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from curator.core.enums import (
    EventType,
    EvidenceKind,
    HarnessStatus,
    LoopStatus,
    LoopStepType,
    PauseStatus,
    ProviderRunStatus,
    RoleName,
)
from curator.core.schema import EventRecord, LoopIterationRecord, PauseRecord
from curator.state.repositories import (
    insert_event,
    insert_loop_iteration,
    insert_loop_run,
    insert_pause_record,
    insert_provider_run,
    load_evidence_refs,
    load_loop_iterations_for_run,
    load_loop_runs_by_status,
    load_pause_records_for_run,
    load_provider_runs_for_run,
)
from curator.state.transaction import transaction


def _interrupted_attempt(pause_records: list[PauseRecord]) -> int:
    """Return the next monotonically increasing interrupted pause attempt."""
    return 1 + sum(1 for pause in pause_records if pause.metadata.get("kind") == "interrupted")


def _anchor_iteration(
    connection: sqlite3.Connection,
    loop_run,
    iterations: list[LoopIterationRecord],
    now: datetime,
) -> LoopIterationRecord:
    """Return the last iteration or persist a marker for an iteration-less crash."""
    if iterations:
        return iterations[-1]
    marker = LoopIterationRecord(
        id=f"{loop_run.id}-interrupted-marker",
        loop_run_id=loop_run.id,
        session_id=loop_run.session_id,
        sequence=0,
        step_type=LoopStepType.PLAN,
        role=RoleName.PM,
        status=HarnessStatus.FAILED,
        started_at=now,
        completed_at=now,
        metadata={"stopped_by": "SYSTEM", "stop_reason": "MACHINE_RESTART"},
    )
    insert_loop_iteration(connection, marker)
    return marker


def _clean_running_execution(
    connection: sqlite3.Connection, loop_run_id: str, now: datetime
) -> None:
    """Mark residual running iterations and provider runs as interrupted failures."""
    for iteration in load_loop_iterations_for_run(connection, loop_run_id):
        if iteration.status is HarnessStatus.RUNNING:
            insert_loop_iteration(
                connection,
                iteration.model_copy(
                    update={
                        "status": HarnessStatus.FAILED,
                        "completed_at": now,
                        "metadata": {
                            **iteration.metadata,
                            "stopped_by": "SYSTEM",
                            "stop_reason": "MACHINE_RESTART",
                        },
                    }
                ),
            )
    for provider_run in load_provider_runs_for_run(connection, loop_run_id):
        if provider_run.status is ProviderRunStatus.RUNNING:
            insert_provider_run(
                connection,
                provider_run.model_copy(
                    update={
                        "status": ProviderRunStatus.FAILED,
                        "completed_at": now,
                        "error_message": "interrupted by crash",
                        "metadata": {
                            **provider_run.metadata,
                            "stopped_by": "SYSTEM",
                            "stop_reason": "MACHINE_RESTART",
                        },
                    }
                ),
            )


def reconcile(
    connection: sqlite3.Connection,
    project_root: Path | str | None = None,
    now: datetime | None = None,
) -> int:
    """Reconcile running or paused loops and return the number recovered."""
    _ = project_root
    timestamp = now or datetime.now(UTC)
    recovered = 0
    candidate_runs = [
        *load_loop_runs_by_status(connection, LoopStatus.RUNNING),
        *load_loop_runs_by_status(connection, LoopStatus.PAUSED),
    ]
    for loop_run in candidate_runs:
        pauses = load_pause_records_for_run(connection, loop_run.id)
        open_pauses = [pause for pause in pauses if pause.status is PauseStatus.OPEN]
        interrupted_open = next(
            (pause for pause in open_pauses if pause.metadata.get("kind") == "interrupted"),
            None,
        )
        if interrupted_open is not None and loop_run.status is LoopStatus.PAUSED:
            continue
        if loop_run.status is LoopStatus.PAUSED and open_pauses:
            continue
        with transaction(connection):
            _clean_running_execution(connection, loop_run.id, timestamp)
            iterations = load_loop_iterations_for_run(connection, loop_run.id)
            anchor = _anchor_iteration(connection, loop_run, iterations, timestamp)
            if loop_run.status is LoopStatus.RUNNING and open_pauses:
                insert_loop_run(
                    connection,
                    loop_run.model_copy(
                        update={"status": LoopStatus.PAUSED, "updated_at": timestamp}
                    ),
                )
            else:
                attempt = _interrupted_attempt(pauses)
                # Claim workspace ownership from the same signal the engine's clean-tree
                # guard uses (_has_implementation_evidence): persisted IMPLEMENTATION
                # evidence, not the mere existence of an IMPLEMENT iteration. A writer that
                # was only RUNNING at crash produced no evidence, so resume must re-run the
                # guard rather than skip it and misattribute a dirty tree to the loop.
                workspace_owned = any(
                    ref.kind is EvidenceKind.IMPLEMENTATION
                    for ref in load_evidence_refs(connection, loop_run.id)
                )
                pause = PauseRecord(
                    id=f"pause-{loop_run.id}-interrupted-{attempt}",
                    loop_run_id=loop_run.id,
                    session_id=loop_run.session_id,
                    iteration_id=anchor.id,
                    task_id=anchor.task_id,
                    reason="Curator recovered an interrupted execution after a machine restart.",
                    question="Resume the interrupted workflow from the writer step?",
                    requested_input="Reply /resume <message> to continue.",
                    resume_mode="continue_current_node",
                    status=PauseStatus.OPEN,
                    created_at=timestamp,
                    metadata={
                        "kind": "interrupted",
                        "attempt": attempt,
                        "stopped_by": "SYSTEM",
                        "stop_reason": "MACHINE_RESTART",
                        "workspace_owned": workspace_owned,
                    },
                )
                insert_pause_record(connection, pause)
                insert_loop_run(
                    connection,
                    loop_run.model_copy(
                        update={"status": LoopStatus.PAUSED, "updated_at": timestamp}
                    ),
                )
            insert_event(
                connection,
                EventRecord(
                    id=f"event-{loop_run.id}-recovery-{timestamp.timestamp()}".replace(".", "-"),
                    session_id=loop_run.session_id,
                    type=EventType.RECOVERY,
                    created_at=timestamp,
                    payload={
                        "kind": "interrupted",
                        "stopped_by": "SYSTEM",
                        "stop_reason": "MACHINE_RESTART",
                    },
                ),
            )
        recovered += 1
    return recovered


def reconcile_project(project_root: Path | str) -> int:
    """Open a project ledger, reconcile it, and close the connection safely."""
    from curator.runtime.lockfile import project_write_lock
    from curator.core.paths import build_curator_paths
    from curator.state.db import connect_database, initialize_database

    paths = build_curator_paths(Path(project_root))
    if not paths.database.exists():
        return 0
    with project_write_lock(project_root):
        connection = connect_database(paths.database)
        try:
            initialize_database(connection)
            return reconcile(connection, project_root)
        finally:
            connection.close()

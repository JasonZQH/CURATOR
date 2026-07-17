"""Verify crash reconciliation and repeated recovery attempts."""

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import sys

import pytest

from curator.core.enums import (
    HarnessStatus,
    LoopStatus,
    LoopStepType,
    PauseStatus,
    ProviderName,
    ProviderRunStatus,
    RoleName,
)
from curator.core.models.loops import LoopIterationRecord
from curator.core.models.runtime import ProviderRunRecord
from curator.scheduler.engine import create_workflow_session
from curator.scheduler.recovery import reconcile, reconcile_project
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_loop_run,
    insert_pause_record,
    load_loop_runs_for_session,
    load_pause_records_for_run,
    insert_loop_iteration,
    insert_provider_run,
)


def test_reconcile_creates_idempotent_and_incrementing_interrupted_pauses(tmp_path):
    """Verify recovery is idempotent and creates a new attempt after resume."""
    now = datetime(2026, 7, 17, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]

    assert reconcile(connection, tmp_path, now) == 1
    assert reconcile(connection, tmp_path, now) == 0
    first = load_pause_records_for_run(connection, loop_run.id)[0]
    assert first.status is PauseStatus.OPEN
    assert first.metadata["attempt"] == 1

    insert_pause_record(
        connection,
        first.model_copy(update={"status": PauseStatus.RESOLVED, "resolved_at": now}),
    )
    insert_loop_run(
        connection,
        loop_run.model_copy(update={"status": LoopStatus.PAUSED, "updated_at": now}),
    )
    assert reconcile(connection, tmp_path, now) == 1
    pauses = load_pause_records_for_run(connection, loop_run.id)
    assert [pause.metadata.get("attempt") for pause in pauses] == [1, 2]
    assert pauses[-1].status is PauseStatus.OPEN
    connection.close()


def test_reconcile_covers_running_open_pause_and_paused_without_cursor(tmp_path):
    """Verify each crash boundary converges to one recoverable paused run."""
    now = datetime(2026, 7, 17, 1, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    running_session = create_workflow_session(connection, tmp_path, created_at=now)
    running = load_loop_runs_for_session(connection, running_session)[0]
    assert reconcile(connection, tmp_path, now) == 1
    running_pauses = load_pause_records_for_run(connection, running.id)
    assert len(running_pauses) == 1

    insert_loop_run(
        connection,
        running.model_copy(update={"status": LoopStatus.RUNNING, "updated_at": now}),
    )
    assert reconcile(connection, tmp_path, now) == 1
    assert load_loop_runs_for_session(connection, running_session)[-1].status is LoopStatus.PAUSED
    assert load_pause_records_for_run(connection, running.id) == running_pauses

    paused_session = create_workflow_session(connection, tmp_path, created_at=now)
    paused = load_loop_runs_for_session(connection, paused_session)[0]
    insert_loop_run(
        connection,
        paused.model_copy(update={"status": LoopStatus.PAUSED, "updated_at": now}),
    )
    assert reconcile(connection, tmp_path, now) == 1
    assert load_pause_records_for_run(connection, paused.id)[0].status is PauseStatus.OPEN
    connection.close()


@pytest.mark.parametrize(
    "boundary",
    [
        "running_no_cursor",
        "running_with_iteration",
        "running_with_provider",
        "running_open_pause",
        "paused_without_cursor",
    ],
)
def test_sigkill_recovery_matrix_releases_lock_and_reconciles(boundary, tmp_path):
    """Verify SIGKILL at five ledger boundaries leaves a resumable cursor."""
    now = datetime(2026, 7, 17, 2, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]

    if boundary in {"running_with_iteration", "running_with_provider"}:
        iteration = LoopIterationRecord(
            id=f"{loop_run.id}-iteration-running",
            loop_run_id=loop_run.id,
            session_id=session_id,
            sequence=1,
            step_type=LoopStepType.IMPLEMENT,
            role=RoleName.ENGINEER,
            status=HarnessStatus.RUNNING,
            started_at=now,
            task_id="task-002-implement",
        )
        insert_loop_iteration(connection, iteration)
        if boundary == "running_with_provider":
            insert_provider_run(
                connection,
                ProviderRunRecord(
                    id=f"provider-{iteration.id}",
                    provider=ProviderName.CODEX,
                    session_id=session_id,
                    loop_run_id=loop_run.id,
                    iteration_id=iteration.id,
                    role=RoleName.ENGINEER,
                    status=ProviderRunStatus.RUNNING,
                    created_at=now,
                ),
            )
    elif boundary == "running_open_pause":
        assert reconcile(connection, tmp_path, now) == 1
        loop_run = load_loop_runs_for_session(connection, session_id)[-1]
        insert_loop_run(
            connection,
            loop_run.model_copy(update={"status": LoopStatus.RUNNING, "updated_at": now}),
        )
    elif boundary == "paused_without_cursor":
        insert_loop_run(
            connection,
            loop_run.model_copy(update={"status": LoopStatus.PAUSED, "updated_at": now}),
        )
    connection.close()

    script = """
from pathlib import Path
import sys
from curator.runtime.lockfile import project_write_lock

with project_write_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    input()
"""
    env = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        os.kill(process.pid, 9)
        assert process.wait(timeout=5) == -9
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert reconcile_project(tmp_path) == 1
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    recovered = load_loop_runs_for_session(connection, session_id)[-1]
    assert recovered.status is LoopStatus.PAUSED
    assert load_pause_records_for_run(connection, loop_run.id)[-1].status is PauseStatus.OPEN
    connection.close()

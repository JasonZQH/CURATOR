"""Verify crash reconciliation and repeated recovery attempts."""

from datetime import UTC, datetime

from curator.core.enums import LoopStatus, PauseStatus
from curator.scheduler.engine import create_workflow_session
from curator.scheduler.recovery import reconcile
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_loop_run,
    insert_pause_record,
    load_loop_runs_for_session,
    load_pause_records_for_run,
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

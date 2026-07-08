"""Verify split state repository modules expose focused persistence APIs."""

from datetime import UTC, datetime

from agentctl.core.enums import LoopStatus, RoleName, SessionMode, TaskStatus
from agentctl.core.paths import build_curator_paths
from agentctl.core.schema import LoopRunRecord, SessionRecord, TaskRecord
from agentctl.state.db import connect_database, initialize_database
from agentctl.state.loops import insert_loop_run, load_loop_runs_for_session
from agentctl.state.repositories import load_session as load_session_from_facade
from agentctl.state.sessions import insert_session, load_session
from agentctl.state.tasks import insert_task, load_tasks_for_session


def test_split_repository_modules_round_trip_core_records(tmp_path):
    """Verify focused repository modules can persist and load core records."""
    now = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    initialize_database(connection)
    session = SessionRecord(
        id="session-boundary-001",
        project_root=tmp_path,
        mode=SessionMode.PLAN_FIRST,
        created_at=now,
        updated_at=now,
    )
    task = TaskRecord(
        id="task-boundary-001",
        session_id=session.id,
        role=RoleName.PM,
        status=TaskStatus.QUEUED,
        title="Plan boundary split",
        created_at=now,
        updated_at=now,
    )
    loop_run = LoopRunRecord(
        id="loop-run-boundary-001",
        session_id=session.id,
        contract_id="contract-boundary-001",
        template_id="coding_delivery_loop",
        status=LoopStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )

    insert_session(connection, session)
    insert_task(connection, task)
    insert_loop_run(connection, loop_run)

    assert load_session(connection, session.id) == session
    assert load_session_from_facade(connection, session.id) == session
    assert load_tasks_for_session(connection, session.id) == [task]
    assert load_loop_runs_for_session(connection, session.id) == [loop_run]

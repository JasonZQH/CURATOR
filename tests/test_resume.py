"""Verify executable resume-from-ledger for paused loops."""

from datetime import UTC, datetime

from agentctl.core.enums import LoopStatus, ProviderBindingStatus, ProviderProfileStatus
from agentctl.core.schema import ProviderProfileRecord, RoleProviderBindingRecord
from agentctl.goals.store import accept_goal, propose_goal, save_goal
from agentctl.app import start_goal_loop, write_init_state
from agentctl.core.enums import ProviderName
from agentctl.core.paths import build_curator_paths
from fakes import CodingDeliveryFakeProvider
from agentctl.runtime.role_pool import ensure_default_role_pool
from agentctl.scheduler.resume import resume_workflow_sync
from agentctl.state.db import connect_database, initialize_database
from agentctl.state.repositories import (
    insert_provider_profile,
    insert_role_provider_binding,
    load_latest_pause_record,
    load_loop_run,
    load_loop_runs_for_session,
    load_pause_records_for_run,
)


def _accepted_revision(tmp_path) -> str:
    """Create and accept a goal revision, returning its id."""
    write_init_state(tmp_path)
    paths = build_curator_paths(tmp_path)
    goal = propose_goal("Add a section to the README")
    save_goal(paths, goal)
    acceptance = accept_goal(paths, goal.id)
    return acceptance.revision_id


def _write_passing_pytest_project(tmp_path) -> None:
    """Create a minimal Python project whose discovered pytest command passes."""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n")


def _bind_live_providers(tmp_path) -> None:
    """Seed a real provider profile and bind writer/reviewer slots to it."""
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    ensure_default_role_pool(connection)
    now = datetime(2026, 7, 8, tzinfo=UTC)
    insert_provider_profile(
        connection,
        ProviderProfileRecord(
            id="codex",
            provider=ProviderName.CODEX,
            label="codex (local CLI)",
            credential_ref="local-cli",
            status=ProviderProfileStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        ),
    )
    for slot_instance in ("writer.default", "reviewer.default"):
        insert_role_provider_binding(
            connection,
            RoleProviderBindingRecord(
                id=f"binding-{slot_instance}-codex",
                role_instance_id=slot_instance,
                provider_profile_id="codex",
                status=ProviderBindingStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
    connection.close()


def test_confirm_gate_resume_completes_loop(tmp_path, monkeypatch):
    """Verify an affirmative resume at the confirm gate finalizes the loop.

    With live providers bound, the single-writer loop pauses at the human
    confirm gate; the deterministic fake stands in for the bound CLI.
    """
    _write_passing_pytest_project(tmp_path)
    revision_id = _accepted_revision(tmp_path)
    _bind_live_providers(tmp_path)

    # Live bindings select the single-writer template; the explicit fake
    # provider stands in for the bound CLI so the run is deterministic.
    snapshot = start_goal_loop(tmp_path, revision_id, provider=CodingDeliveryFakeProvider())
    loop_run = snapshot.loop_runs[-1]

    assert loop_run.template_id == "single_writer_loop"
    assert loop_run.status is LoopStatus.PAUSED

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    pause = load_latest_pause_record(connection)
    assert pause is not None
    assert pause.resume_mode == "confirm_gate"

    resumed = resume_workflow_sync(connection, loop_run.id, "yes")
    refreshed = load_loop_run(connection, loop_run.id)
    open_pauses = [
        record
        for record in load_pause_records_for_run(connection, loop_run.id)
        if record.status.value == "open"
    ]
    connection.close()

    assert resumed
    assert refreshed.status is LoopStatus.DONE
    assert open_pauses == []


def test_resume_refuses_when_no_open_pause(tmp_path):
    """Verify resume returns False when there is no open pause to continue."""
    from agentctl.scheduler.engine import create_workflow_session

    write_init_state(tmp_path)

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path)
    loop_run = load_loop_runs_for_session(connection, session_id)[-1]
    resumed = resume_workflow_sync(connection, loop_run.id, "yes")
    connection.close()

    assert resumed is False

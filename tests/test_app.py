"""Verify application orchestration boundaries."""

import yaml

from curator.app import (
    preview_init,
    render_workflow,
    run_workflow_snapshot,
    write_init_state,
)
from curator.core.enums import LoopDecisionType, LoopStatus, StopCondition
from curator.core.paths import build_curator_paths
from curator.init.proposal import build_init_proposal
from curator.state.db import connect_database
from curator.state.repositories import load_loop_runs_for_session
from fakes import CodingDeliveryFakeProvider


def test_preview_init_returns_proposal_without_creating_state(tmp_path):
    """Verify app init preview is read-only and renderable."""
    output = preview_init(tmp_path)

    assert "Curator init proposal" in output
    assert "- .curator/team/roles/pm/role.md" in output
    assert "- .curator/curator.sqlite" in output
    assert not (tmp_path / ".curator").exists()


def test_write_init_state_creates_state_and_reports_skipped_files(tmp_path):
    """Verify app init write creates state and preserves existing files."""
    first_result = write_init_state(tmp_path)
    second_result = write_init_state(tmp_path)

    assert first_result.created_files_count > 0
    assert first_result.skipped_files_count == 0
    assert second_result.created_files_count == 0
    assert second_result.skipped_files_count > 0
    assert (tmp_path / ".curator" / "curator.sqlite").exists()


def test_run_workflow_snapshot_returns_done_snapshot(tmp_path):
    """Verify app orchestration returns the completed fake workflow snapshot."""
    write_init_state(tmp_path)

    snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())

    assert snapshot.loop_runs[-1].status is LoopStatus.DONE
    assert snapshot.loop_decisions[-1].decision is LoopDecisionType.STOP_DONE
    assert snapshot.loop_decisions[-1].stop_condition is StopCondition.DONE_CRITERIA_MET
    assert len(snapshot.evidence_refs) == 4


def test_run_workflow_snapshot_reads_edited_role_contracts(tmp_path):
    """Verify app runtime decisions use project-local edited role contracts."""
    write_init_state(tmp_path)
    paths = build_curator_paths(tmp_path)
    engineer_contract = paths.role_contract_file("engineer")
    parsed = yaml.safe_load(engineer_contract.read_text())
    parsed["handoff_rules"][0]["reason"] = "Project-specific QA gate."
    engineer_contract.write_text(yaml.safe_dump(parsed, sort_keys=False))

    snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())

    assert snapshot.loop_decisions[1].decision is LoopDecisionType.CONTINUE_TO_QA
    assert snapshot.loop_decisions[1].reason == "Project-specific QA gate."


def test_run_workflow_snapshot_falls_back_when_contract_yaml_is_invalid(tmp_path):
    """Verify invalid editable contracts do not block runtime workflows."""
    write_init_state(tmp_path)
    paths = build_curator_paths(tmp_path)
    paths.role_contract_file("engineer").write_text("id: engineer\nhandoff_rules: [\n")

    snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())

    assert snapshot.loop_runs[-1].status is LoopStatus.DONE
    assert snapshot.loop_decisions[1].reason == (
        "Validate implementation before PM confirmation."
    )


def test_render_workflow_returns_terminal_lines(tmp_path):
    """Verify app orchestration can return terminal workflow lines."""
    write_init_state(tmp_path)

    lines = render_workflow(tmp_path, CodingDeliveryFakeProvider())

    assert "Loop: coding_delivery_loop" in lines
    assert "Decision: stop_done" in lines
    assert "Stop: done_criteria_met" in lines
    assert "Evidence: 4" in lines


def test_run_workflow_snapshot_creates_unique_runs(tmp_path):
    """Verify repeated app fake runs do not overwrite prior durable sessions."""
    write_init_state(tmp_path)

    first_snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())
    second_snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())
    connection = connect_database(build_init_proposal(tmp_path).paths.database)

    assert first_snapshot.session.id != second_snapshot.session.id
    assert first_snapshot.loop_runs[-1].id != second_snapshot.loop_runs[-1].id
    assert len(load_loop_runs_for_session(connection, first_snapshot.session.id)) == 1
    assert len(load_loop_runs_for_session(connection, second_snapshot.session.id)) == 1


def test_run_workflow_snapshot_accepts_explicit_session_id(tmp_path):
    """Verify app fake runs can use a caller-selected session id."""
    write_init_state(tmp_path)

    snapshot = run_workflow_snapshot(
        tmp_path,
        CodingDeliveryFakeProvider(),
        session_id="session-demo-001",
    )

    assert snapshot.session.id == "session-demo-001"
    assert snapshot.loop_runs[-1].session_id == "session-demo-001"

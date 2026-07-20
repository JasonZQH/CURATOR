"""Verify workflow snapshot terminal rendering."""

from datetime import UTC, datetime

from curator.core.enums import EvidenceKind, PauseStatus
from curator.core.schema import PauseRecord
from curator.core.schema import RoleContract
from curator.loops.compiler import compile_coding_delivery_plan
from curator.roles.registry import default_role_contracts
from curator.scheduler.engine import create_workflow_session
from curator.scheduler.snapshots import load_workflow_snapshot
from curator.state.db import connect_database, initialize_database
from curator.tui.workflow_panel import render_workflow_lines


def test_render_workflow_lines_includes_dynamic_tasks_and_role_selections(tmp_path):
    """Verify terminal rendering explains dynamic role selection from snapshot data."""
    now = datetime(2026, 6, 25, 15, 30, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    contracts = default_role_contracts()
    contracts["security_reviewer"] = RoleContract(
        id="security_reviewer",
        display_name="Security Reviewer",
        responsibilities=["Review auth, token, secret, and permission boundaries."],
        when_to_involve=["auth", "secret", "permission"],
        expected_evidence_kinds=[EvidenceKind.ARTIFACT],
        forbidden_actions=["edit-product-scope"],
        capability_tags=["security-review", "auth", "secrets"],
    )
    compiled_plan = compile_coding_delivery_plan(
        session_id="session-001",
        contract_id="contract-coding-delivery",
        role_contracts=contracts,
        task_signals=["auth", "secret"],
    )
    session_id = create_workflow_session(
        connection,
        tmp_path,
        created_at=now,
        compiled_plan=compiled_plan,
    )
    snapshot = load_workflow_snapshot(connection, session_id)

    lines = render_workflow_lines(snapshot)

    assert "Loop: coding_delivery_loop" in lines
    assert "Tasks:" in lines
    assert "- pm: queued - Plan coding delivery" in lines
    assert "- qa: queued - Security Reviewer review [security_reviewer]" in lines
    assert "Selected Roles:" in lines
    assert "- Security Reviewer: auth, secret (score 2)" in lines
    assert "  Selected security_reviewer because it matched: auth, secret." in lines
    assert "Evidence: 0" in lines


def test_render_workflow_lines_hides_resolved_pauses(tmp_path):
    """Verify a resumed loop no longer renders its historical pause as active."""
    now = datetime(2026, 6, 25, 15, 30, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)
    snapshot = load_workflow_snapshot(connection, session_id)
    snapshot = snapshot.model_copy(
        update={
            "pause_records": [
                PauseRecord(
                    id="pause-resolved",
                    loop_run_id=snapshot.loop_runs[0].id,
                    session_id=session_id,
                    iteration_id="iteration-1",
                    task_id="task-1",
                    reason="old pause",
                    question="old question",
                    requested_input="/resume yes",
                    resume_mode="confirm_gate",
                    status=PauseStatus.RESOLVED,
                    created_at=now,
                    resolved_at=now,
                )
            ]
        }
    )

    lines = render_workflow_lines(snapshot)

    assert "Paused:" not in lines
    connection.close()

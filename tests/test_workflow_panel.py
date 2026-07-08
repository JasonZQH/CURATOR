"""Verify workflow snapshot terminal rendering."""

from datetime import UTC, datetime

from agentctl.core.enums import EvidenceKind
from agentctl.core.schema import RoleContract
from agentctl.loops.compiler import compile_coding_delivery_plan
from agentctl.roles.registry import default_role_contracts
from agentctl.scheduler.engine import create_workflow_session
from agentctl.scheduler.snapshots import load_workflow_snapshot
from agentctl.state.db import connect_database, initialize_database
from agentctl.tui.workflow_panel import render_workflow_lines


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

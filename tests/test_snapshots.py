"""Verify workflow snapshot read models."""

from datetime import UTC, datetime

from agentctl.core.enums import EvidenceKind
from agentctl.core.schema import RoleContract
from agentctl.loops.compiler import compile_coding_delivery_plan
from agentctl.roles.registry import default_role_contracts
from agentctl.scheduler.engine import create_workflow_session
from agentctl.scheduler.snapshots import load_workflow_snapshot
from agentctl.state.db import connect_database, initialize_database


def test_load_workflow_snapshot_includes_role_selection_ledger(tmp_path):
    """Verify snapshots expose selected role ledger records for UI consumers."""
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
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

    assert snapshot.session.id == session_id
    assert [task.title for task in snapshot.tasks] == [
        "Plan coding delivery",
        "Implement coding delivery",
        "Security Reviewer review",
        "Validate coding delivery",
        "Confirm coding delivery",
    ]
    assert snapshot.loop_runs[0].template_id == "coding_delivery_loop"
    assert len(snapshot.role_selections) == 1
    assert snapshot.role_selections[0].role_id == "security_reviewer"
    assert snapshot.role_selections[0].matched_signals == ["auth", "secret"]

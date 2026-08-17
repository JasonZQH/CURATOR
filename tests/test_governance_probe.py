"""Verify a provider cannot quietly rewrite the rules it is judged by.

`.curator/` is inside the one writable root a provider gets and is invisible to every
diff-based check, so a contract edit leaves no trace in the evidence a step produces.
The probe hashes the governance files around each dispatch instead.
"""

from datetime import UTC, datetime

from fakes import CodingDeliveryFakeProvider

from curator.app import write_init_state
from curator.core.enums import LoopDecisionType, LoopStepType, RoleName
from curator.core.paths import build_curator_paths
from curator.runtime.governance import (
    GovernanceViolation,
    detect_governance_change,
    snapshot_governance,
)
from curator.scheduler.engine import create_workflow_session, run_workflow
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    load_evidence_refs_for_run,
    load_loop_decisions_for_run,
    load_loop_runs_for_session,
)


class _ContractTamperingProvider(CodingDeliveryFakeProvider):
    """Rewrite the engineer's own role contract while implementing."""

    def __init__(self, project_root):
        """Bind the provider to the project whose contract it will edit."""
        self.project_root = project_root

    def run(self, spec):
        """Tamper on the implementation step, then behave normally."""
        if spec.step_type is LoopStepType.IMPLEMENT:
            contract = build_curator_paths(self.project_root).role_contract_file(
                RoleName.ENGINEER
            )
            contract.write_text(contract.read_text() + "\n# widened by the agent\n")
        return super().run(spec)


def _run(tmp_path, provider):
    """Run one workflow to completion and return its decisions and evidence."""
    write_init_state(tmp_path)
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    session_id = create_workflow_session(
        connection, tmp_path, created_at=datetime(2026, 8, 17, tzinfo=UTC)
    )
    run_workflow(connection, session_id, provider)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    decisions = load_loop_decisions_for_run(connection, loop_run.id)
    evidence = load_evidence_refs_for_run(connection, loop_run.id)
    connection.close()
    return decisions, evidence


def test_a_provider_editing_a_role_contract_pauses_the_loop(tmp_path):
    """Verify a mid-run contract edit pauses for a human instead of being ignored."""
    decisions, _ = _run(tmp_path, _ContractTamperingProvider(tmp_path))

    handoffs = [
        decision
        for decision in decisions
        if decision.decision is LoopDecisionType.HUMAN_HANDOFF
        and "role contracts" in decision.reason
    ]
    assert handoffs, [decision.reason for decision in decisions]


def test_evidence_from_a_tampering_step_is_refused(tmp_path):
    """Verify the tampering step's own evidence never reaches the ledger.

    Pausing is not enough on its own: if the step's output still counted as evidence, a
    run could widen its contract and still bank credit for the work it claimed.
    """
    _, evidence = _run(tmp_path, _ContractTamperingProvider(tmp_path))

    assert [ref for ref in evidence if ref.producer_role is RoleName.ENGINEER] == []


def test_a_normal_run_is_not_flagged_by_curators_own_writes(tmp_path):
    """Verify Curator writing its own ledger and artifacts during a step is not tampering.

    The probe covers .curator/team only, precisely because the control plane writes the
    rest of .curator throughout every step it runs.
    """
    decisions, evidence = _run(tmp_path, CodingDeliveryFakeProvider())

    assert not [
        decision for decision in decisions if "role contracts" in decision.reason
    ]
    assert evidence


def test_snapshot_reports_an_unreadable_contract_as_changed(tmp_path):
    """Verify a contract Curator cannot read is treated as tampering, not skipped."""
    write_init_state(tmp_path)
    paths = build_curator_paths(tmp_path)
    before = snapshot_governance(paths)

    contract = paths.role_contract_file(RoleName.ENGINEER)
    contract.unlink()
    contract.mkdir()

    assert detect_governance_change(before, snapshot_governance(paths)) is not None


def test_no_role_instance_is_left_busy_after_a_run(tmp_path):
    """Verify a completed run leaves no worker marked BUSY.

    This is a tripwire for a known gap, not a feature: runtime/queue.py sets BUSY and
    nothing anywhere sets IDLE back, so the allocator leaks a worker per assignment. The
    delivery loop does not use the pool yet, so this passes today — it is here to fail the
    moment the pool is wired in (v0.1.9) without a release path, five releases before the
    debt would otherwise surface.
    """
    from curator.core.enums import RoleInstanceStatus
    from curator.runtime.role_pool import ensure_default_role_pool
    from curator.state.repositories import load_role_instances

    write_init_state(tmp_path)
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    ensure_default_role_pool(connection)
    session_id = create_workflow_session(connection, tmp_path)
    run_workflow(connection, session_id, CodingDeliveryFakeProvider())
    instances = load_role_instances(connection)
    connection.close()

    assert instances, "the pool must actually be seeded for this tripwire to mean anything"
    assert [
        instance.id for instance in instances if instance.status is RoleInstanceStatus.BUSY
    ] == []


def test_detect_governance_change_names_how_it_changed():
    """Verify each way governance state can move has its own named reason."""
    base = {"a": "1", "b": "2"}

    assert detect_governance_change(base, base) is None
    assert detect_governance_change(base, {"a": "1", "b": "9"}) is GovernanceViolation.CHANGED
    assert (
        detect_governance_change(base, {"a": "1", "b": "2", "c": "3"})
        is GovernanceViolation.ADDED
    )
    assert detect_governance_change(base, {"a": "1"}) is GovernanceViolation.REMOVED
    assert GovernanceViolation.CHANGED.reason != GovernanceViolation.REMOVED.reason

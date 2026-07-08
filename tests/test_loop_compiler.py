"""Verify loop templates compile into scheduler-ready plans."""

from agentctl.core.enums import (
    EvidenceKind,
    LoopDecisionType,
    LoopStepType,
    RoleName,
    StopCondition,
)
from agentctl.core.schema import RoleContract
from agentctl.loops.compiler import compile_coding_delivery_plan
from agentctl.roles.registry import default_role_contracts


def test_compile_coding_delivery_plan_outputs_dynamic_scheduler_steps():
    """Verify the default loop compiles into executable step contracts."""
    plan = compile_coding_delivery_plan(
        session_id="session-001",
        contract_id="contract-001",
    )

    assert plan.session_id == "session-001"
    assert plan.contract_id == "contract-001"
    assert plan.template_id == "coding_delivery_loop"
    assert [step.step_type for step in plan.steps] == [
        LoopStepType.PLAN,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.CONFIRM,
    ]
    assert [step.role for step in plan.steps] == [
        RoleName.PM,
        RoleName.ENGINEER,
        RoleName.QA,
        RoleName.PM,
    ]
    assert [step.role_id for step in plan.steps] == [
        "pm",
        "engineer",
        "qa",
        "pm",
    ]
    assert [step.task_id for step in plan.steps] == [
        "task-001-plan",
        "task-002-implement",
        "task-003-validate",
        "task-004-confirm",
    ]
    assert [step.decision_on_success for step in plan.steps] == [
        LoopDecisionType.CONTINUE_TO_ENGINEER,
        LoopDecisionType.CONTINUE_TO_QA,
        LoopDecisionType.CONTINUE_TO_PM,
        LoopDecisionType.STOP_DONE,
    ]
    assert plan.steps[0].required_evidence_kinds == []
    assert plan.steps[1].required_evidence_kinds == [EvidenceKind.PLAN]
    assert plan.steps[2].required_evidence_kinds == [
        EvidenceKind.PLAN,
        EvidenceKind.IMPLEMENTATION,
    ]
    assert plan.steps[3].required_evidence_kinds == [
        EvidenceKind.PLAN,
        EvidenceKind.IMPLEMENTATION,
        EvidenceKind.VALIDATION,
    ]
    assert plan.steps[-1].stop_condition_on_success is StopCondition.DONE_CRITERIA_MET
    assert plan.steps[0].metadata["role_display_name"] == "PM"
    assert plan.steps[0].metadata["role_capability_tags"] == [
        "planning",
        "acceptance-criteria",
        "alignment-confirmation",
    ]
    assert plan.steps[1].metadata["role_display_name"] == "Engineer"
    assert plan.steps[2].metadata["role_display_name"] == "QA"


def test_compile_coding_delivery_plan_inserts_selected_reviewer_roles():
    """Verify selected custom roles are compiled between implementation and QA."""
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

    plan = compile_coding_delivery_plan(
        session_id="session-001",
        contract_id="contract-001",
        role_contracts=contracts,
        task_signals=["auth", "secret"],
    )

    assert [step.role_id for step in plan.steps] == [
        "pm",
        "engineer",
        "security_reviewer",
        "qa",
        "pm",
    ]
    assert [step.sequence for step in plan.steps] == [1, 2, 3, 4, 5]
    assert plan.steps[2].task_id == "task-003-security-reviewer"
    assert plan.steps[2].task_title == "Security Reviewer review"
    assert plan.steps[2].step_type is LoopStepType.VALIDATE
    assert plan.steps[2].role is RoleName.QA
    assert plan.steps[2].required_evidence_kinds == [
        EvidenceKind.PLAN,
        EvidenceKind.IMPLEMENTATION,
    ]
    assert plan.steps[2].decision_on_success is LoopDecisionType.CONTINUE_TO_QA
    assert plan.steps[2].metadata["selection_reason"] == (
        "Selected security_reviewer because it matched: auth, secret."
    )


def test_compile_single_writer_plan_builds_functional_slots():
    """Verify the single-writer plan compiles writer, verifier, reviewer, and gate."""
    from agentctl.core.enums import StepExecutorType
    from agentctl.loops.compiler import compile_single_writer_plan

    plan = compile_single_writer_plan(
        session_id="session-writer-001",
        contract_id="contract-writer-001",
    )

    assert plan.template_id == "single_writer_loop"
    assert [step.step_type for step in plan.steps] == [
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.REVIEW,
        LoopStepType.CONFIRM,
    ]
    assert [step.executor for step in plan.steps] == [
        StepExecutorType.PROVIDER,
        StepExecutorType.VERIFIER,
        StepExecutorType.PROVIDER,
        StepExecutorType.HUMAN_GATE,
    ]
    assert [step.slot for step in plan.steps] == ["writer", None, "reviewer", None]
    assert plan.steps[0].max_retries == 2

    writer, verifier, reviewer, gate = plan.steps
    assert verifier.metadata["retry_target_step_id"] == writer.id
    assert reviewer.required_evidence_kinds == [
        EvidenceKind.IMPLEMENTATION,
        EvidenceKind.VALIDATION,
    ]
    assert [step.decision_on_success for step in plan.steps] == [
        LoopDecisionType.CONTINUE,
        LoopDecisionType.CONTINUE,
        LoopDecisionType.CONTINUE,
        LoopDecisionType.STOP_DONE,
    ]

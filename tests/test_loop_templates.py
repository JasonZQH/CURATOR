"""Verify Curator-owned loop templates."""

from curator.core.enums import (
    EvidenceKind,
    LoopDecisionType,
    LoopStepType,
    RoleName,
    StopCondition,
)
from curator.loops.templates import coding_delivery_loop, role_for_step, template_requires_evidence


def test_coding_delivery_loop_has_fixed_phase0_steps():
    """Verify the Phase 0 coding loop is PM to Engineer to QA to PM."""
    template = coding_delivery_loop()

    assert template.id == "coding_delivery_loop"
    assert template.steps == [
        LoopStepType.PLAN,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.CONFIRM,
    ]
    assert role_for_step(template, LoopStepType.PLAN) is RoleName.PM
    assert role_for_step(template, LoopStepType.IMPLEMENT) is RoleName.ENGINEER
    assert role_for_step(template, LoopStepType.VALIDATE) is RoleName.QA
    assert role_for_step(template, LoopStepType.CONFIRM) is RoleName.PM


def test_coding_delivery_loop_requires_pm_confirmation_after_qa_validation():
    """Verify PM confirms QA results against PM plan before stop_done."""
    template = coding_delivery_loop()
    done_criteria_ids = {criteria.id for criteria in template.done_criteria}

    assert template_requires_evidence(template, LoopStepType.VALIDATE, EvidenceKind.PLAN)
    assert template_requires_evidence(template, LoopStepType.VALIDATE, EvidenceKind.IMPLEMENTATION)
    assert not template_requires_evidence(template, LoopStepType.VALIDATE, EvidenceKind.VALIDATION)
    assert template_requires_evidence(template, LoopStepType.CONFIRM, EvidenceKind.PLAN)
    assert template_requires_evidence(template, LoopStepType.CONFIRM, EvidenceKind.IMPLEMENTATION)
    assert template_requires_evidence(template, LoopStepType.CONFIRM, EvidenceKind.VALIDATION)
    assert not template_requires_evidence(template, LoopStepType.CONFIRM, EvidenceKind.PM_CONFIRMATION)
    assert "pm-confirmation-received" in done_criteria_ids
    assert "qa-validation-passed" in done_criteria_ids
    assert LoopDecisionType.CONTINUE_TO_PM in template.allowed_decisions
    assert LoopDecisionType.STOP_DONE in template.allowed_decisions
    assert StopCondition.DONE_CRITERIA_MET in template.stop_conditions

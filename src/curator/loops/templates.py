"""Define Curator-owned loop templates for Phase 0 workflows."""

from curator.core.enums import (
    EvidenceKind,
    LoopDecisionType,
    LoopStepType,
    RoleName,
    StopCondition,
)
from curator.core.schema import DoneCriteria, GuideRef, LoopTemplate, SensorRef

CODING_DELIVERY_LOOP_ID = "coding_delivery_loop"
SINGLE_WRITER_LOOP_ID = "single_writer_loop"

_STEP_ROLES = {
    LoopStepType.PLAN: RoleName.PM,
    LoopStepType.IMPLEMENT: RoleName.ENGINEER,
    LoopStepType.VALIDATE: RoleName.QA,
    LoopStepType.CONFIRM: RoleName.PM,
}

_REQUIRED_EVIDENCE = {
    LoopStepType.PLAN: [],
    LoopStepType.IMPLEMENT: [EvidenceKind.PLAN],
    LoopStepType.VALIDATE: [
        EvidenceKind.PLAN,
        EvidenceKind.IMPLEMENTATION,
    ],
    LoopStepType.CONFIRM: [
        EvidenceKind.PLAN,
        EvidenceKind.IMPLEMENTATION,
        EvidenceKind.VALIDATION,
    ],
}

_SINGLE_WRITER_STEP_ROLES = {
    LoopStepType.IMPLEMENT: RoleName.ENGINEER,
    LoopStepType.VALIDATE: RoleName.QA,
    LoopStepType.REVIEW: RoleName.QA,
    LoopStepType.CONFIRM: RoleName.PM,
}

# The reviewer deliberately receives the goal plus artifacts, never the
# writer's transcript, so review happens with fresh context.
_SINGLE_WRITER_REQUIRED_EVIDENCE = {
    LoopStepType.IMPLEMENT: [],
    LoopStepType.VALIDATE: [EvidenceKind.IMPLEMENTATION],
    LoopStepType.REVIEW: [
        EvidenceKind.IMPLEMENTATION,
        EvidenceKind.VALIDATION,
    ],
    LoopStepType.CONFIRM: [
        EvidenceKind.IMPLEMENTATION,
        EvidenceKind.VALIDATION,
        EvidenceKind.REVIEW,
    ],
}


def coding_delivery_loop() -> LoopTemplate:
    """Return the Phase 0 coding loop with PM confirmation after QA validation."""
    return LoopTemplate(
        id=CODING_DELIVERY_LOOP_ID,
        name="Coding delivery loop",
        steps=[
            LoopStepType.PLAN,
            LoopStepType.IMPLEMENT,
            LoopStepType.VALIDATE,
            LoopStepType.CONFIRM,
        ],
        done_criteria=[
            DoneCriteria(
                id="qa-validation-passed",
                description="QA validation evidence must pass before PM confirmation is requested.",
            ),
            DoneCriteria(
                id="pm-confirmation-received",
                description=(
                    "PM must confirm QA validation results align with the original PM plan "
                    "before stop_done is allowed."
                ),
            ),
        ],
        guide_refs=[
            GuideRef(
                id="pm-role",
                title="PM role contract",
                uri=".curator/team/roles/pm/role.md",
            ),
            GuideRef(
                id="engineer-role",
                title="Engineer role contract",
                uri=".curator/team/roles/engineer/role.md",
            ),
            GuideRef(
                id="qa-role",
                title="QA role contract",
                uri=".curator/team/roles/qa/role.md",
            ),
        ],
        sensor_refs=[
            SensorRef(
                id="pm-plan-evidence",
                description="PM must produce plan evidence before engineering starts.",
                required_evidence_kind=EvidenceKind.PLAN,
            ),
            SensorRef(
                id="engineer-implementation-evidence",
                description="Engineer must produce implementation evidence before QA starts.",
                required_evidence_kind=EvidenceKind.IMPLEMENTATION,
            ),
            SensorRef(
                id="qa-validation-evidence",
                description=(
                    "QA must produce validation evidence from PM plan evidence and Engineer "
                    "implementation evidence before PM confirmation is requested."
                ),
                required_evidence_kind=EvidenceKind.VALIDATION,
            ),
            SensorRef(
                id="pm-confirmation-evidence",
                description=(
                    "PM must produce confirmation evidence from PM plan, Engineer "
                    "implementation, and QA validation evidence before stop_done is allowed."
                ),
                required_evidence_kind=EvidenceKind.PM_CONFIRMATION,
            ),
        ],
        allowed_decisions=[
            LoopDecisionType.CONTINUE_TO_ENGINEER,
            LoopDecisionType.CONTINUE_TO_QA,
            LoopDecisionType.CONTINUE_TO_PM,
            LoopDecisionType.RETRY_IMPLEMENTATION,
            LoopDecisionType.RETRY_VALIDATION,
            LoopDecisionType.HUMAN_HANDOFF,
            LoopDecisionType.STOP_DONE,
            LoopDecisionType.STOP_FAILED,
        ],
        stop_conditions=[
            StopCondition.DONE_CRITERIA_MET,
            StopCondition.MAX_ITERATIONS_REACHED,
            StopCondition.VALIDATION_FAILED,
            StopCondition.PROVIDER_FAILED,
            StopCondition.HUMAN_HANDOFF_REQUESTED,
            StopCondition.CONTRACT_VIOLATION,
        ],
    )


def single_writer_loop() -> LoopTemplate:
    """Return the writer/verifier/reviewer loop with a human confirm gate."""
    return LoopTemplate(
        id=SINGLE_WRITER_LOOP_ID,
        name="Single writer loop",
        steps=[
            LoopStepType.IMPLEMENT,
            LoopStepType.VALIDATE,
            LoopStepType.REVIEW,
            LoopStepType.CONFIRM,
        ],
        done_criteria=[
            DoneCriteria(
                id="verification-passed",
                description="Deterministic verification must pass before review.",
            ),
            DoneCriteria(
                id="review-completed",
                description="A fresh-context reviewer must assess the diff and verification.",
            ),
            DoneCriteria(
                id="user-confirmation-received",
                description="The user must confirm delivery before stop_done is allowed.",
            ),
        ],
        sensor_refs=[
            SensorRef(
                id="writer-implementation-evidence",
                description="The writer run must produce implementation evidence.",
                required_evidence_kind=EvidenceKind.IMPLEMENTATION,
            ),
            SensorRef(
                id="verifier-validation-evidence",
                description="The verifier must produce validation evidence from real checks.",
                required_evidence_kind=EvidenceKind.VALIDATION,
            ),
            SensorRef(
                id="reviewer-review-evidence",
                description="The reviewer must produce review evidence with fresh context.",
                required_evidence_kind=EvidenceKind.REVIEW,
            ),
        ],
        allowed_decisions=[
            LoopDecisionType.CONTINUE,
            LoopDecisionType.RETRY_STEP,
            LoopDecisionType.HUMAN_HANDOFF,
            LoopDecisionType.STOP_DONE,
            LoopDecisionType.STOP_FAILED,
        ],
        stop_conditions=[
            StopCondition.DONE_CRITERIA_MET,
            StopCondition.MAX_ITERATIONS_REACHED,
            StopCondition.VALIDATION_FAILED,
            StopCondition.PROVIDER_FAILED,
            StopCondition.HUMAN_HANDOFF_REQUESTED,
            StopCondition.CONTRACT_VIOLATION,
        ],
    )


_TEMPLATE_STEP_ROLES = {
    CODING_DELIVERY_LOOP_ID: _STEP_ROLES,
    SINGLE_WRITER_LOOP_ID: _SINGLE_WRITER_STEP_ROLES,
}

_TEMPLATE_REQUIRED_EVIDENCE = {
    CODING_DELIVERY_LOOP_ID: _REQUIRED_EVIDENCE,
    SINGLE_WRITER_LOOP_ID: _SINGLE_WRITER_REQUIRED_EVIDENCE,
}


def role_for_step(template: LoopTemplate, step_type: LoopStepType) -> RoleName:
    """Return the Phase 0 role assigned to a step in a known loop template."""
    step_roles = _TEMPLATE_STEP_ROLES.get(template.id)
    if step_roles is None:
        raise ValueError(f"Unknown loop template: {template.id}")
    if step_type not in template.steps:
        raise ValueError(f"Step is not part of template {template.id}: {step_type.value}")

    return step_roles[step_type]


def template_requires_evidence(
    template: LoopTemplate,
    step_type: LoopStepType,
    evidence_kind: EvidenceKind,
) -> bool:
    """Return whether a template step requires a specific evidence kind."""
    required = _TEMPLATE_REQUIRED_EVIDENCE.get(template.id)
    if required is None or step_type not in template.steps:
        return False

    return evidence_kind in required[step_type]

"""Convert provider outputs into typed harness evidence references."""

from datetime import datetime

from curator.core.enums import EvidenceKind, LoopStepType
from curator.core.schema import (
    EngineerImplementationOutput,
    EvidenceRef,
    HarnessRunSpec,
    PMConfirmationOutput,
    PMPlanOutput,
    QAValidationOutput,
)
from curator.providers.base import RoleOutput


def evidence_kind_for_output(output: RoleOutput) -> EvidenceKind:
    """Return the evidence kind represented by one provider output schema."""
    if isinstance(output, PMPlanOutput):
        return EvidenceKind.PLAN
    if isinstance(output, EngineerImplementationOutput):
        return EvidenceKind.IMPLEMENTATION
    if isinstance(output, QAValidationOutput):
        return EvidenceKind.VALIDATION
    if isinstance(output, PMConfirmationOutput):
        return EvidenceKind.PM_CONFIRMATION

    raise TypeError(f"Unsupported provider output: {type(output).__name__}")


def _summary_for_output(output: RoleOutput) -> str:
    """Return the human summary carried by a provider output schema."""
    return output.summary


def build_evidence_ref(
    spec: HarnessRunSpec,
    output: RoleOutput,
    created_at: datetime,
) -> EvidenceRef:
    """Create one evidence reference for a harness provider output."""
    evidence_kind = evidence_kind_for_output(output)
    return EvidenceRef(
        id=f"evidence-{spec.id}",
        session_id=spec.session_id,
        loop_run_id=spec.loop_run_id,
        iteration_id=spec.iteration_id,
        kind=evidence_kind,
        uri=f"provider-output://{spec.role.value}/{spec.step_type.value}/{spec.id}",
        summary=_summary_for_output(output),
        producer_role=spec.role,
        created_at=created_at,
        content_hash=f"sha256:{spec.id}:{evidence_kind.value}",
    )


def expected_step_for_output(output: RoleOutput) -> LoopStepType:
    """Return the loop step that matches one provider output schema."""
    if isinstance(output, PMPlanOutput):
        return LoopStepType.PLAN
    if isinstance(output, EngineerImplementationOutput):
        return LoopStepType.IMPLEMENT
    if isinstance(output, QAValidationOutput):
        return LoopStepType.VALIDATE
    if isinstance(output, PMConfirmationOutput):
        return LoopStepType.CONFIRM

    raise TypeError(f"Unsupported provider output: {type(output).__name__}")

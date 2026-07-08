"""Provide fake provider fixtures used by scheduler and harness tests."""

from datetime import UTC, datetime

from agentctl.core.enums import EvidenceKind, LoopStepType, ProviderName, RoleName
from agentctl.core.schema import (
    EngineerImplementationOutput,
    EvidenceRef,
    HarnessRunSpec,
    PMConfirmationOutput,
    PMPlanOutput,
    QAValidationOutput,
)
from agentctl.providers.contracts import ProviderRunRequest, ProviderRunResponse


class CodingDeliveryFakeProvider:
    """Return deterministic role outputs for a full coding delivery loop."""

    provider_name = ProviderName.CODEX
    provider_profile_id = "codex-test"
    provider_session_id = "provider-session-codex-test"

    def run(self, spec: HarnessRunSpec):
        """Return the role output matching the requested loop step."""
        if spec.role is RoleName.PM and spec.step_type is LoopStepType.PLAN:
            return PMPlanOutput(
                summary="Plan is ready.",
                tasks=["Implement the requested change."],
                done_criteria=["Validation passes."],
            )
        if spec.role is RoleName.ENGINEER and spec.step_type is LoopStepType.IMPLEMENT:
            return EngineerImplementationOutput(
                summary="Implementation is complete.",
                changed_files=["src/app.py"],
                test_commands=["pytest"],
            )
        if spec.role is RoleName.QA and spec.step_type is LoopStepType.VALIDATE:
            return QAValidationOutput(
                passed=True,
                summary="Validation passed.",
                checks=["pytest"],
            )
        if spec.role is RoleName.QA and spec.step_type is LoopStepType.REVIEW:
            request = ProviderRunRequest.from_harness_spec(spec)
            evidence = EvidenceRef(
                id=f"evidence-review-{spec.iteration_id}",
                session_id=spec.session_id,
                loop_run_id=spec.loop_run_id,
                iteration_id=spec.iteration_id,
                kind=EvidenceKind.REVIEW,
                uri=f"provider-output://qa/review/{spec.id}",
                summary="Review passed.",
                producer_role=RoleName.QA,
                created_at=datetime(2026, 7, 8, tzinfo=UTC),
            )
            response = ProviderRunResponse.succeeded(
                request,
                ProviderName.CODEX,
                output={"summary": "Review passed."},
            )
            return response.model_copy(update={"evidence_refs": [evidence]})
        if spec.role is RoleName.PM and spec.step_type is LoopStepType.CONFIRM:
            return PMConfirmationOutput(
                confirmed=True,
                summary="PM confirms delivery.",
                aligned_done_criteria=["Validation passes."],
            )
        raise ValueError(
            "CodingDeliveryFakeProvider cannot run role and step pair: "
            f"{spec.role.value}/{spec.step_type.value}"
        )

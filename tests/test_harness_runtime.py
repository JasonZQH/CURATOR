"""Verify harness context, artifact, and runtime behavior."""

from datetime import UTC, datetime

import pytest

from agentctl.core.enums import (
    EvidenceKind,
    HarnessStatus,
    LoopStepType,
    ProviderErrorKind,
    ProviderName,
    RoleName,
)
from agentctl.core.schema import (
    EvidenceRef,
    HarnessRunSpec,
    PMConfirmationOutput,
    PMPlanOutput,
    QAValidationOutput,
)
from agentctl.harness.artifacts import build_evidence_ref
from agentctl.harness.context import build_context_refs
from agentctl.harness.runtime import run_harness
from agentctl.loops.templates import coding_delivery_loop
from agentctl.providers.contracts import ProviderRunRequest, ProviderRunResponse


class StaticProvider:
    """Return one preconfigured provider output for harness tests."""

    def __init__(self, output):
        """Store the output that run will return."""
        self.output = output
        self.seen_specs = []

    def run(self, spec):
        """Record the harness spec and return the configured output."""
        self.seen_specs.append(spec)
        return self.output


def _evidence(kind: EvidenceKind, role: RoleName, suffix: str) -> EvidenceRef:
    """Build one test evidence reference with stable identifiers."""
    return EvidenceRef(
        id=f"evidence-{suffix}",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id=f"iteration-{suffix}",
        kind=kind,
        uri=f"provider-output://{suffix}",
        summary=f"{suffix} evidence",
        producer_role=role,
        created_at=datetime(2026, 6, 25, 11, 0, tzinfo=UTC),
    )


def test_context_refs_route_prior_evidence_to_engineer_qa_and_pm_confirmation():
    """Verify harness context includes the required prior evidence for each step."""
    template = coding_delivery_loop()
    plan = _evidence(EvidenceKind.PLAN, RoleName.PM, "plan")
    implementation = _evidence(EvidenceKind.IMPLEMENTATION, RoleName.ENGINEER, "implementation")
    validation = _evidence(EvidenceKind.VALIDATION, RoleName.QA, "validation")
    confirmation = _evidence(EvidenceKind.PM_CONFIRMATION, RoleName.PM, "confirmation")
    refs = [plan, implementation, validation, confirmation]

    engineer_refs = build_context_refs(template, LoopStepType.IMPLEMENT, refs)
    qa_refs = build_context_refs(template, LoopStepType.VALIDATE, refs)
    pm_refs = build_context_refs(template, LoopStepType.CONFIRM, refs)

    assert engineer_refs == [plan]
    assert qa_refs == [plan, implementation]
    assert pm_refs == [plan, implementation, validation]


def test_build_evidence_ref_maps_role_outputs_to_evidence_kinds():
    """Verify role output schemas become typed evidence references."""
    now = datetime(2026, 6, 25, 11, 30, tzinfo=UTC)
    spec = HarnessRunSpec(
        id="harness-qa",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-qa",
        role=RoleName.QA,
        step_type=LoopStepType.VALIDATE,
        task_id="task-qa",
    )

    evidence = build_evidence_ref(
        spec,
        QAValidationOutput(passed=True, summary="QA passed.", checks=["tests"]),
        now,
    )

    assert evidence.kind is EvidenceKind.VALIDATION
    assert evidence.uri == "provider-output://qa/validate/harness-qa"
    assert evidence.summary == "QA passed."
    assert evidence.producer_role is RoleName.QA


def test_harness_runtime_returns_structured_result_without_repo_writes(tmp_path, monkeypatch):
    """Verify harness execution returns evidence and does not write project files."""
    monkeypatch.chdir(tmp_path)
    now = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
    spec = HarnessRunSpec(
        id="harness-pm-confirm",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-pm-confirm",
        role=RoleName.PM,
        step_type=LoopStepType.CONFIRM,
        task_id="task-pm-confirm",
    )
    provider = StaticProvider(
        PMConfirmationOutput(
            confirmed=True,
            summary="PM confirms QA output aligns with the plan.",
            aligned_done_criteria=["qa-validation-passed"],
        )
    )

    result = run_harness(spec, provider, created_at=now)

    assert provider.seen_specs == [spec]
    assert result.status is HarnessStatus.SUCCEEDED
    assert result.role is RoleName.PM
    assert result.step_type is LoopStepType.CONFIRM
    assert result.evidence_refs[0].kind is EvidenceKind.PM_CONFIRMATION
    assert result.output["confirmed"] is True
    assert list(tmp_path.iterdir()) == []


def test_harness_runtime_rejects_mismatched_provider_output():
    """Verify provider output must match the requested loop step."""
    spec = HarnessRunSpec(
        id="harness-qa",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-qa",
        role=RoleName.QA,
        step_type=LoopStepType.VALIDATE,
        task_id="task-qa",
    )
    provider = StaticProvider(
        PMPlanOutput(summary="Wrong output.", tasks=["task"], done_criteria=["done"])
    )

    with pytest.raises(ValueError, match="Provider output does not match"):
        run_harness(spec, provider)


def test_harness_runtime_maps_failed_provider_response_to_failed_status():
    """Verify a failed typed provider response is not recorded as harness success."""
    spec = HarnessRunSpec(
        id="harness-engineer",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-engineer",
        role=RoleName.ENGINEER,
        step_type=LoopStepType.IMPLEMENT,
        task_id="task-engineer",
    )
    request = ProviderRunRequest.from_harness_spec(spec)
    provider = StaticProvider(
        ProviderRunResponse.failed(
            request,
            ProviderName.CODEX,
            error_kind=ProviderErrorKind.PROVIDER_UNAVAILABLE,
            error_message="quota exhausted",
        )
    )

    result = run_harness(spec, provider)

    assert result.status is HarnessStatus.FAILED
    assert result.metadata["error_kind"] == "provider_unavailable"
    assert result.metadata["error_message"] == "quota exhausted"

"""Verify deterministic runtime scheduler decisions."""

from datetime import UTC, datetime

from curator.core.enums import (
    EvidenceKind,
    HarnessStatus,
    LoopDecisionType,
    LoopStepType,
    StopCondition,
)
from curator.core.schema import EvidenceRef, HarnessRunResult
from curator.loops.compiler import compile_coding_delivery_plan
from curator.roles.registry import default_role_contracts
from curator.scheduler.decision import decide_runtime


def _step(step_type: LoopStepType):
    """Return one compiled step from the default coding delivery plan."""
    plan = compile_coding_delivery_plan(
        session_id="session-001",
        contract_id="contract-coding-delivery",
    )
    return next(step for step in plan.steps if step.step_type is step_type)


def _result(step_type: LoopStepType, evidence_refs: list[EvidenceRef]):
    """Return a harness result with caller-selected evidence refs."""
    return HarnessRunResult(
        spec_id=f"harness-{step_type.value}",
        status=HarnessStatus.SUCCEEDED,
        role=_step(step_type).role,
        step_type=step_type,
        evidence_refs=evidence_refs,
        output={"summary": "Fake output."},
    )


def test_decide_runtime_continues_when_success_has_evidence():
    """Verify successful harness output follows the matching handoff rule."""
    step = _step(LoopStepType.IMPLEMENT)
    evidence = EvidenceRef(
        id="evidence-001",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-001",
        kind=step.required_evidence_kinds[0]
        if step.required_evidence_kinds
        else _step(LoopStepType.PLAN).required_evidence_kinds[0],
        uri="provider-output://evidence",
        summary="Fake evidence.",
        producer_role=step.role,
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    decision = decide_runtime(step, _result(LoopStepType.IMPLEMENT, [evidence]))

    assert decision.decision is LoopDecisionType.CONTINUE_TO_QA
    assert decision.stop_condition is None
    assert decision.reason == "Validate implementation before PM confirmation."


def test_decide_runtime_uses_custom_handoff_rule_reason():
    """Verify runtime routing reads handoff rules from supplied role contracts."""
    step = _step(LoopStepType.IMPLEMENT)
    contracts = default_role_contracts()
    contracts["engineer"] = contracts["engineer"].model_copy(
        update={
            "handoff_rules": [
                rule.model_copy(update={"reason": "Custom QA gate from contract."})
                for rule in contracts["engineer"].handoff_rules
            ]
        }
    )
    evidence = EvidenceRef(
        id="evidence-implementation-custom",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-implementation",
        kind=EvidenceKind.IMPLEMENTATION,
        uri="provider-output://implementation",
        summary="Implementation evidence.",
        producer_role=step.role,
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    decision = decide_runtime(
        step,
        _result(LoopStepType.IMPLEMENT, [evidence]),
        role_contracts=contracts,
    )

    assert decision.decision is LoopDecisionType.CONTINUE_TO_QA
    assert decision.reason == "Custom QA gate from contract."


def test_decide_runtime_stops_failed_when_provider_failed():
    """Verify provider failures stop the loop with provider_failed."""
    step = _step(LoopStepType.PLAN)

    decision = decide_runtime(step, None, provider_error=RuntimeError("provider down"))

    assert decision.decision is LoopDecisionType.STOP_FAILED
    assert decision.stop_condition is StopCondition.PROVIDER_FAILED
    assert decision.reason == "Provider failed during plan: provider down"


def test_decide_runtime_stops_failed_when_success_has_no_evidence():
    """Verify successful harness runs without evidence are contract violations."""
    step = _step(LoopStepType.PLAN)

    decision = decide_runtime(step, _result(LoopStepType.PLAN, []))

    assert decision.decision is LoopDecisionType.STOP_FAILED
    assert decision.stop_condition is StopCondition.CONTRACT_VIOLATION
    assert decision.reason == "plan step succeeded without evidence."


def test_decide_runtime_retries_implementation_when_qa_validation_fails():
    """Verify failed QA validation routes back to Engineer implementation."""
    step = _step(LoopStepType.VALIDATE)
    evidence = EvidenceRef(
        id="evidence-validation",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-validation",
        kind=step.required_evidence_kinds[0],
        uri="provider-output://validation",
        summary="QA found a failure.",
        producer_role=step.role,
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    result = _result(LoopStepType.VALIDATE, [evidence]).model_copy(
        update={"output": {"passed": False, "summary": "QA failed."}}
    )

    decision = decide_runtime(step, result)

    assert decision.decision is LoopDecisionType.RETRY_IMPLEMENTATION
    assert decision.stop_condition is StopCondition.VALIDATION_FAILED
    assert decision.reason == "Return failed validation feedback for implementation repair."


def test_decide_runtime_routes_confirmed_pm_output_to_done_from_contract():
    """Verify PM confirmation completion is resolved through a handoff rule."""
    step = _step(LoopStepType.CONFIRM)
    evidence = EvidenceRef(
        id="evidence-pm-confirmation",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-confirm",
        kind=EvidenceKind.PM_CONFIRMATION,
        uri="provider-output://confirmation",
        summary="PM confirmation.",
        producer_role=step.role,
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    result = _result(LoopStepType.CONFIRM, [evidence]).model_copy(
        update={"output": {"confirmed": True, "summary": "PM accepted."}}
    )

    decision = decide_runtime(step, result)

    assert decision.decision is LoopDecisionType.STOP_DONE
    assert decision.stop_condition is StopCondition.DONE_CRITERIA_MET
    assert decision.reason == "Complete the loop after PM confirms QA evidence."


def test_decide_runtime_pauses_when_pm_rejects_confirmation():
    """Verify a rejected PM confirmation pauses instead of completing as done."""
    step = _step(LoopStepType.CONFIRM)
    evidence = EvidenceRef(
        id="evidence-pm-rejection",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-confirm",
        kind=EvidenceKind.PM_CONFIRMATION,
        uri="provider-output://confirmation",
        summary="PM confirmation.",
        producer_role=step.role,
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    result = _result(LoopStepType.CONFIRM, [evidence]).model_copy(
        update={"output": {"confirmed": False, "summary": "PM rejected delivery."}}
    )

    decision = decide_runtime(step, result)

    assert decision.decision is LoopDecisionType.HUMAN_HANDOFF
    assert decision.stop_condition is StopCondition.HUMAN_HANDOFF_REQUESTED
    assert decision.reason == "PM rejected delivery confirmation; pausing for user input."


def test_decide_runtime_stops_failed_for_failed_provider_response_status():
    """Verify a failed harness status stops the loop with provider_failed."""
    step = _step(LoopStepType.IMPLEMENT)
    result = _result(LoopStepType.IMPLEMENT, []).model_copy(
        update={
            "status": HarnessStatus.FAILED,
            "metadata": {
                "error_kind": "provider_unavailable",
                "error_message": "quota exhausted",
            },
        }
    )

    decision = decide_runtime(step, result)

    assert decision.decision is LoopDecisionType.HUMAN_HANDOFF
    assert decision.stop_condition is StopCondition.HUMAN_HANDOFF_REQUESTED
    assert "quota exhausted" in decision.reason


def test_decide_runtime_pauses_for_recoverable_failed_provider_response():
    """Verify recoverable provider failure kinds pause for user input."""
    step = _step(LoopStepType.IMPLEMENT)
    result = _result(LoopStepType.IMPLEMENT, []).model_copy(
        update={
            "status": HarnessStatus.FAILED,
            "metadata": {"error_kind": "timeout", "error_message": "provider timed out"},
        }
    )

    decision = decide_runtime(step, result)

    assert decision.decision is LoopDecisionType.HUMAN_HANDOFF
    assert decision.stop_condition is StopCondition.HUMAN_HANDOFF_REQUESTED


def test_ledger_event_payload_redacts_secrets_in_output_chunks():
    """Verify provider stdout persisted to the ledger cannot carry a bare token in cleartext."""
    from curator.providers.events import ProviderEvent, ProviderEventKind
    from curator.scheduler.engine import _ledger_event_payload

    event = ProviderEvent(
        kind=ProviderEventKind.OUTPUT_CHUNK,
        provider_run_id="provider-1",
        payload={"text": "provider said sk-abcdef0123456789abcdef then continued"},
    )

    payload = _ledger_event_payload(event)

    assert "sk-abcdef0123456789abcdef" not in payload["text"]
    assert "[REDACTED]" in payload["text"]

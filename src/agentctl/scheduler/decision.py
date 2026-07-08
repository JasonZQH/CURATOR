"""Decide scheduler runtime transitions from harness outcomes."""

from dataclasses import dataclass

from agentctl.core.enums import (
    HarnessStatus,
    LoopDecisionType,
    LoopStepType,
    StepExecutorType,
    StopCondition,
)
from agentctl.core.schema import CompiledLoopStep, HarnessRunResult, RoleContract
from agentctl.roles.registry import default_role_contracts
from agentctl.scheduler.routing import resolve_handoff

_PAUSED_ERROR_KINDS = {"invalid_output", "permission_denied", "timeout", "cancelled"}


@dataclass(frozen=True)
class RuntimeDecision:
    """Describe the deterministic scheduler decision after one harness run."""

    decision: LoopDecisionType
    stop_condition: StopCondition | None
    reason: str
    retry_target_step_id: str | None = None


def _provider_error_reason(step: CompiledLoopStep, provider_error: Exception) -> str:
    """Return the durable reason for a provider failure."""
    return f"Provider failed during {step.step_type.value}: {provider_error}"


def _qa_validation_failed(result: HarnessRunResult) -> bool:
    """Return whether a QA validation result explicitly failed validation."""
    return result.step_type is LoopStepType.VALIDATE and result.output.get("passed") is False


def _confirmation_rejected(result: HarnessRunResult) -> bool:
    """Return whether a PM confirmation result explicitly rejected delivery."""
    return result.step_type is LoopStepType.CONFIRM and result.output.get("confirmed") is False


def _failed_response_decision(step: CompiledLoopStep, result: HarnessRunResult) -> RuntimeDecision:
    """Return the decision for a provider response that reported failure."""
    error_kind = str(result.metadata.get("error_kind", ""))
    error_message = str(result.metadata.get("error_message") or "Provider reported a failed run.")
    if error_kind in _PAUSED_ERROR_KINDS:
        return RuntimeDecision(
            decision=LoopDecisionType.HUMAN_HANDOFF,
            stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
            reason=(
                f"Provider reported {error_kind} during {step.step_type.value}; "
                "pausing for user input."
            ),
        )

    return RuntimeDecision(
        decision=LoopDecisionType.STOP_FAILED,
        stop_condition=StopCondition.PROVIDER_FAILED,
        reason=f"Provider reported failure during {step.step_type.value}: {error_message}",
    )


def decide_runtime(
    step: CompiledLoopStep,
    result: HarnessRunResult | None,
    provider_error: Exception | None = None,
    role_contracts: dict[str, RoleContract] | None = None,
) -> RuntimeDecision:
    """Return the scheduler-owned decision for a harness run result."""
    if provider_error is not None:
        return RuntimeDecision(
            decision=LoopDecisionType.STOP_FAILED,
            stop_condition=StopCondition.PROVIDER_FAILED,
            reason=_provider_error_reason(step, provider_error),
        )

    if result is not None and result.status is HarnessStatus.FAILED:
        return _failed_response_decision(step, result)

    if result is None or not result.evidence_refs:
        return RuntimeDecision(
            decision=LoopDecisionType.STOP_FAILED,
            stop_condition=StopCondition.CONTRACT_VIOLATION,
            reason=f"{step.step_type.value} step succeeded without evidence.",
        )

    # Role handoff rules belong to the legacy pipeline; slot- or
    # verifier-executed steps route by queue position and retry targets.
    routes_by_contract = step.executor is StepExecutorType.PROVIDER and step.slot is None
    if routes_by_contract:
        contracts = role_contracts or default_role_contracts()
        handoff = resolve_handoff(step, result, contracts)
        if handoff is not None:
            return RuntimeDecision(
                decision=handoff.decision,
                stop_condition=handoff.stop_condition,
                reason=handoff.reason,
            )

    if _confirmation_rejected(result):
        return RuntimeDecision(
            decision=LoopDecisionType.HUMAN_HANDOFF,
            stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
            reason="PM rejected delivery confirmation; pausing for user input.",
        )

    if _qa_validation_failed(result):
        retry_target = step.metadata.get("retry_target_step_id")
        if step.executor is StepExecutorType.VERIFIER and retry_target:
            return RuntimeDecision(
                decision=LoopDecisionType.RETRY_STEP,
                stop_condition=StopCondition.VALIDATION_FAILED,
                reason="Verification failed; retrying the writer step.",
                retry_target_step_id=str(retry_target),
            )
        return RuntimeDecision(
            decision=LoopDecisionType.RETRY_IMPLEMENTATION,
            stop_condition=StopCondition.VALIDATION_FAILED,
            reason="QA validation failed; retrying implementation.",
        )

    return RuntimeDecision(
        decision=step.decision_on_success,
        stop_condition=step.stop_condition_on_success,
        reason=f"{step.step_type.value} step completed successfully.",
    )

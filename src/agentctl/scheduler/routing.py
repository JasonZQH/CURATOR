"""Resolve runtime role handoffs from role collaboration contracts."""

from dataclasses import dataclass

from agentctl.core.enums import LoopDecisionType, LoopStepType, RoleName, StopCondition
from agentctl.core.schema import (
    CompiledLoopStep,
    HarnessRunResult,
    RoleContract,
    RoleHandoffRule,
)


@dataclass(frozen=True)
class HandoffResolution:
    """Describe a resolved handoff rule as a scheduler decision."""

    decision: LoopDecisionType
    stop_condition: StopCondition | None
    reason: str


def _trigger_for_result(result: HarnessRunResult) -> str:
    """Return the handoff trigger represented by one harness result."""
    if result.step_type is LoopStepType.PLAN:
        return "scope_approved"
    if result.step_type is LoopStepType.IMPLEMENT:
        return "implementation_complete"
    if result.step_type is LoopStepType.VALIDATE:
        return "validation_failed" if result.output.get("passed") is False else "validation_passed"
    if result.step_type is LoopStepType.CONFIRM:
        return (
            "confirmation_rejected"
            if result.output.get("confirmed") is False
            else "confirmation_accepted"
        )

    return result.step_type.value


def _decision_for_rule(
    rule: RoleHandoffRule,
    step: CompiledLoopStep,
) -> tuple[LoopDecisionType, StopCondition | None]:
    """Return the scheduler enum decision represented by a handoff rule."""
    if rule.to_role_id == RoleName.ENGINEER.value:
        if rule.trigger == "validation_failed":
            return LoopDecisionType.RETRY_IMPLEMENTATION, StopCondition.VALIDATION_FAILED
        return LoopDecisionType.CONTINUE_TO_ENGINEER, None
    if rule.to_role_id == RoleName.QA.value:
        return LoopDecisionType.CONTINUE_TO_QA, None
    if rule.to_role_id == RoleName.PM.value:
        return LoopDecisionType.CONTINUE_TO_PM, None
    if rule.to_role_id == "done":
        return LoopDecisionType.STOP_DONE, StopCondition.DONE_CRITERIA_MET

    return step.decision_on_success, step.stop_condition_on_success


def _find_handoff_rule(
    contract: RoleContract,
    trigger: str,
) -> RoleHandoffRule | None:
    """Return the handoff rule matching a trigger from a role contract."""
    return next((rule for rule in contract.handoff_rules if rule.trigger == trigger), None)


def resolve_handoff(
    step: CompiledLoopStep,
    result: HarnessRunResult,
    role_contracts: dict[str, RoleContract],
) -> HandoffResolution | None:
    """Resolve a runtime handoff decision from role contracts and provider output."""
    contract = role_contracts.get(step.role_id)
    if contract is None:
        return None

    rule = _find_handoff_rule(contract, _trigger_for_result(result))
    if rule is None:
        return None

    decision, stop_condition = _decision_for_rule(rule, step)
    return HandoffResolution(
        decision=decision,
        stop_condition=stop_condition,
        reason=rule.reason,
    )

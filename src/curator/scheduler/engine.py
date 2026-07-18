"""Run compiled loop plans through the deterministic Phase 0 scheduler."""

import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from curator.core.enums import (
    EvidenceKind,
    HarnessStatus,
    LoopDecisionType,
    LoopStatus,
    LoopStepType,
    PauseStatus,
    ProviderName,
    ProviderErrorKind,
    ProviderRunStatus,
    StepExecutorType,
    StopCondition,
    TaskStatus,
)
from curator.core.schema import (
    CompiledLoopPlan,
    CompiledLoopStep,
    EventRecord,
    EvidenceRef,
    HarnessRunResult,
    HarnessRunSpec,
    LoopDecisionRecord,
    LoopIterationRecord,
    LoopRunRecord,
    PauseRecord,
    ProviderRunRecord,
    RoleContract,
    SessionRecord,
    TaskRecord,
    GoalContract,
)
from curator.context.packaging import build_context_package
from curator.harness.runtime import run_harness_async
from curator.harness.verifier import (
    VerificationSpec,
    build_validation_evidence,
    discover_verification_commands,
    run_verification,
)
from curator.harness.workspace import (
    WorkspaceDirtyError,
    capture_baseline,
    require_clean_baseline,
)
from curator.memory.distill import record_decision_memory
from curator.loops.compiler import compile_coding_delivery_plan
from curator.providers.contracts import (
    ProviderCancelledError,
    ProviderRunRequest,
    classify_provider_error,
)
from curator.providers.redact import redact_error, redact_secrets
from curator.providers.base import Provider
from curator.providers.driver import ProviderDriver, driver_for_provider
from curator.providers.events import (
    ProviderEvent,
    ProviderEventCallback,
    ProviderEventKind,
)
from curator.providers.registry import ProviderConfigurationError
from curator.scheduler.ids import (
    new_session_id,
    scoped_harness_id,
    scoped_iteration_id,
    scoped_task_id,
)
from curator.scheduler.session_factory import build_workflow_session_records
from curator.scheduler.step_writer import (
    write_loop_completion,
    write_loop_pause,
    write_step_events,
    write_step_message,
)
from curator.state.repositories import (
    insert_event,
    insert_evidence_ref,
    insert_loop_decision,
    insert_loop_iteration,
    insert_loop_run,
    insert_pause_record,
    insert_provider_run,
    insert_role_selection,
    insert_session,
    insert_task,
    load_loop_runs_for_session,
    load_session,
    load_tasks_for_session,
)
from curator.state.transaction import transaction
from curator.core.enums import EventType
from curator.scheduler.decision import RuntimeDecision, decide_runtime
from curator.scheduler.cancellation import CancellationToken

MAX_ITERATIONS = 12
DEFAULT_MAX_STEP_RETRIES = 1

# Resolves the async driver for one compiled step (slot → provider binding).
DriverResolver = Callable[[CompiledLoopStep], ProviderDriver]

_RETRY_DECISIONS = (
    LoopDecisionType.RETRY_IMPLEMENTATION,
    LoopDecisionType.RETRY_STEP,
)
_ADVANCE_DECISIONS = (
    LoopDecisionType.CONTINUE,
    # Deprecated routing values advance the queue like CONTINUE so that role
    # handoff rules loaded from older contracts cannot stall execution.
    LoopDecisionType.CONTINUE_TO_ENGINEER,
    LoopDecisionType.CONTINUE_TO_QA,
    LoopDecisionType.CONTINUE_TO_PM,
)


def _timestamp(created_at: datetime | None) -> datetime:
    """Return the supplied timestamp or a current UTC timestamp."""
    return created_at or datetime.now(UTC)


@dataclass(frozen=True)
class LoopExecutionContext:
    """Group immutable collaborators for one running loop."""

    connection: sqlite3.Connection
    session: SessionRecord
    loop_run: LoopRunRecord
    plan: CompiledLoopPlan
    provider: Provider | None
    driver: ProviderDriver | None
    tasks_by_id: dict[str, TaskRecord]
    role_contracts: dict[str, RoleContract] | None
    goal_contract: GoalContract | None
    created_at: datetime | None
    on_event: ProviderEventCallback | None = None
    driver_resolver: "DriverResolver | None" = None
    cancellation: CancellationToken | None = None

    def driver_for_step(self, step: CompiledLoopStep) -> ProviderDriver:
        """Return the driver for one step, honoring slot bindings when present."""
        if self.driver_resolver is not None:
            return self.driver_resolver(step)
        if self.driver is None:
            raise ProviderConfigurationError(
                "No provider driver configured. Connect one with /provider add "
                "<name> in the Curator shell (or `curator provider add <name>` "
                "in your terminal)."
            )
        return self.driver


@dataclass
class LoopExecutionState:
    """Track mutable execution state for one running loop."""

    pending_steps: list[CompiledLoopStep] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    run_sequence: int = 0
    retry_counts: dict[str, int] = field(default_factory=dict)
    retry_task_ids: set[str] = field(default_factory=set)
    workspace_owned: bool = False


@dataclass(frozen=True)
class StepOutcome:
    """Describe the persisted result of executing one compiled step."""

    runtime_decision: RuntimeDecision
    retry_step: CompiledLoopStep | None
    iteration: LoopIterationRecord
    decision_record: LoopDecisionRecord
    completed_at: datetime


def load_compiled_plan_for_run(loop_run: LoopRunRecord) -> CompiledLoopPlan | None:
    """Return the compiled plan persisted with a loop run, when present."""
    raw_plan = loop_run.metadata.get("compiled_plan")
    if not raw_plan:
        return None

    return CompiledLoopPlan.model_validate(raw_plan)


_LEDGER_EVENT_TYPES = {
    ProviderEventKind.STARTED: EventType.PROVIDER_RUN_STARTED,
    ProviderEventKind.TOOL_CALL: EventType.PROVIDER_TOOL_CALL,
    ProviderEventKind.PERMISSION_REQUEST: EventType.PROVIDER_PERMISSION_REQUEST,
    ProviderEventKind.OUTPUT_CHUNK: EventType.PROVIDER_OUTPUT_CHUNK,
    ProviderEventKind.COMPLETED: EventType.PROVIDER_RUN_COMPLETED,
    ProviderEventKind.FAILED: EventType.PROVIDER_RUN_COMPLETED,
}


def _ledger_event_payload(event: ProviderEvent) -> dict:
    """Return the durable ledger payload for a provider event.

    Provider stdout can echo credentials, so OUTPUT_CHUNK text is scrubbed before it
    is persisted (errors are already redacted via redact_error); redact then head-cap
    so the persisted chunk never contains a secret in cleartext.
    """
    payload = {"kind": event.kind.value, "label": event.label}
    if event.kind is ProviderEventKind.OUTPUT_CHUNK:
        payload["text"] = redact_secrets(str(event.payload.get("text", "")))[:4096]
    return payload


def _ledger_event_recorder(
    ctx: LoopExecutionContext,
    spec: HarnessRunSpec,
    task_id: str,
) -> ProviderEventCallback:
    """Return a callback that ledgers provider events and forwards them."""
    counter = {"count": 0}

    def _record(event: ProviderEvent) -> None:
        """Ledger one provider event and forward it to the caller callback."""
        event_type = _LEDGER_EVENT_TYPES.get(event.kind)
        if event_type is not None:
            counter["count"] += 1
            insert_event(
                ctx.connection,
                EventRecord(
                    id=f"event-{spec.iteration_id}-provider-{counter['count']:03d}",
                    session_id=ctx.session.id,
                    task_id=task_id,
                    type=event_type,
                    created_at=_timestamp(ctx.created_at),
                    payload=_ledger_event_payload(event),
                ),
            )
        if ctx.on_event is not None:
            ctx.on_event(event)

    return _record


def _default_compiled_plan(
    session_id: str,
    role_contracts: dict[str, RoleContract] | None = None,
) -> CompiledLoopPlan:
    """Return the default compiled plan for coding delivery sessions."""
    return compile_coding_delivery_plan(
        session_id=session_id,
        contract_id="contract-coding-delivery",
        role_contracts=role_contracts,
    )


def _context_refs_for_step(
    step: CompiledLoopStep,
    evidence_refs: list[EvidenceRef],
    include_latest_validation: bool = False,
) -> list[EvidenceRef]:
    """Return prior evidence required by a compiled loop step.

    Retried steps also receive the latest validation evidence so the retry
    attempt can see why the previous attempt failed.
    """
    refs = [
        evidence
        for evidence in evidence_refs
        if evidence.kind in step.required_evidence_kinds
    ]
    if include_latest_validation and EvidenceKind.VALIDATION not in step.required_evidence_kinds:
        validations = [
            evidence for evidence in evidence_refs if evidence.kind is EvidenceKind.VALIDATION
        ]
        if validations:
            refs.append(validations[-1])
    return refs


def create_workflow_session(
    connection: sqlite3.Connection,
    project_root: Path | str,
    created_at: datetime | None = None,
    compiled_plan: CompiledLoopPlan | None = None,
    session_id: str | None = None,
    role_contracts: dict[str, RoleContract] | None = None,
) -> str:
    """Create the durable session, tasks, and loop run for one workflow."""
    now = _timestamp(created_at)
    resolved_session_id = session_id or (compiled_plan.session_id if compiled_plan else None)
    plan = compiled_plan or _default_compiled_plan(
        resolved_session_id or new_session_id(),
        role_contracts,
    )
    skeleton = build_workflow_session_records(
        project_root=project_root,
        created_at=now,
        compiled_plan=plan,
    )

    with transaction(connection):
        insert_session(connection, skeleton.session)
        for task in skeleton.tasks:
            insert_task(connection, task)
        insert_loop_run(connection, skeleton.loop_run)
        for selection in skeleton.role_selections:
            insert_role_selection(connection, selection)
    return skeleton.session.id


def _retry_implementation_step(plan: CompiledLoopPlan) -> CompiledLoopStep:
    """Return the compiled Engineer implementation step for retry routing."""
    return next(step for step in plan.steps if step.step_type is LoopStepType.IMPLEMENT)


def _retry_target_step(
    plan: CompiledLoopPlan,
    decision: RuntimeDecision,
    current_step: CompiledLoopStep,
) -> CompiledLoopStep:
    """Return the compiled step a retry decision should re-run."""
    _ = current_step
    if decision.retry_target_step_id:
        for candidate in plan.steps:
            if candidate.id == decision.retry_target_step_id:
                return candidate

    return _retry_implementation_step(plan)


def _max_retries_for_step(step: CompiledLoopStep) -> int:
    """Return the retry budget carried by one compiled step."""
    raw = step.metadata.get("max_retries", step.max_retries)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_STEP_RETRIES


def _paused_after_repeated_failure_decision() -> RuntimeDecision:
    """Return a human handoff decision after repeated validation failure."""
    return RuntimeDecision(
        decision=LoopDecisionType.HUMAN_HANDOFF,
        stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
        reason="Repeated validation failure; pausing for user input.",
    )


def _max_iterations_decision() -> RuntimeDecision:
    """Return a human handoff decision when the iteration budget is exhausted."""
    return RuntimeDecision(
        decision=LoopDecisionType.HUMAN_HANDOFF,
        stop_condition=StopCondition.MAX_ITERATIONS_REACHED,
        reason="Maximum loop iterations reached; pausing for user input.",
    )


def _provider_name(provider: Provider) -> ProviderName:
    """Return the stable provider name for a provider instance."""
    provider_name = getattr(provider, "provider_name", None)
    if isinstance(provider_name, ProviderName):
        return provider_name
    if isinstance(provider_name, str):
        return ProviderName(provider_name)
    nested_provider = getattr(provider, "provider", None)
    if nested_provider is not None and nested_provider is not provider:
        return _provider_name(nested_provider)

    raise ProviderConfigurationError("Provider identity is missing a provider_name.")


def _provider_profile_id(provider: Provider) -> str | None:
    """Return the provider profile id exposed by a provider instance."""
    provider_profile_id = getattr(provider, "provider_profile_id", None)
    if isinstance(provider_profile_id, str):
        return provider_profile_id
    nested_provider = getattr(provider, "provider", None)
    if nested_provider is not None and nested_provider is not provider:
        return _provider_profile_id(nested_provider)
    return None


def _provider_session_id(provider: Provider) -> str | None:
    """Return the provider session id exposed by a provider instance."""
    provider_session_id = getattr(provider, "provider_session_id", None)
    if isinstance(provider_session_id, str):
        return provider_session_id
    nested_provider = getattr(provider, "provider", None)
    if nested_provider is not None and nested_provider is not provider:
        return _provider_session_id(nested_provider)
    return None


def _provider_quota_status(provider: Provider) -> str | None:
    """Return the provider quota status exposed by a provider instance."""
    quota_status = getattr(provider, "quota_status", None)
    if hasattr(quota_status, "value"):
        return str(quota_status.value)
    if isinstance(quota_status, str):
        return quota_status
    nested_provider = getattr(provider, "provider", None)
    if nested_provider is not None and nested_provider is not provider:
        return _provider_quota_status(nested_provider)
    return None


def _pause_reason_for_provider_error(provider_error: Exception) -> str | None:
    """Return a pause reason only for known recoverable provider failures."""
    if isinstance(provider_error, ProviderConfigurationError):
        return f"{provider_error} Pausing until a real provider is configured."
    if isinstance(provider_error, WorkspaceDirtyError):
        return f"{provider_error} Pausing so existing changes are not misattributed."
    if isinstance(provider_error, FileNotFoundError):
        return f"Provider executable is unavailable: {provider_error}. Pausing for setup."
    if isinstance(provider_error, ConnectionError):
        return f"Provider connection is unavailable: {provider_error}. Pausing for setup."
    if isinstance(provider_error, ProviderCancelledError):
        return "Provider was cancelled; pausing for user input."
    error_kind = classify_provider_error(provider_error)
    if error_kind.value == "invalid_output":
        return "Provider invalid output; pausing for user input."
    if error_kind.value == "permission_denied":
        return "Provider permission denied; pausing for user input."
    if error_kind.value == "timeout":
        return "Provider timed out; pausing for user input."
    if error_kind.value == "cancelled":
        return "Provider was cancelled; pausing for user input."
    # An untyped exception classified as provider_unavailable is an unexpected provider
    # bug, not a recognized recoverable failure: return None so the run STOP_FAILEDs
    # (see test_provider_failure_matrix_stops_on_untyped_runtime_error). The pause-worthy
    # provider_unavailable in decision._PAUSED_ERROR_KINDS is the result-reported kind.
    return None


def _pause_record_for_decision(
    loop_run_id: str,
    iteration: LoopIterationRecord,
    decision: LoopDecisionRecord,
) -> PauseRecord:
    """Build one durable pause cursor from a human handoff decision."""
    overrides = decision.metadata
    return PauseRecord(
        id=f"pause-{decision.id}",
        loop_run_id=loop_run_id,
        session_id=iteration.session_id,
        iteration_id=iteration.id,
        task_id=iteration.task_id,
        reason=decision.reason,
        question=str(
            overrides.get("pause_question", "How should Curator proceed from this paused node?")
        ),
        requested_input=str(
            overrides.get(
                "pause_requested_input",
                "Reply with natural language guidance or a revised scope.",
            )
        ),
        resume_mode=str(overrides.get("pause_resume_mode", "continue_current_node")),
        status=PauseStatus.OPEN,
        created_at=decision.created_at,
    )


def _provider_run_record(
    provider: Provider,
    spec: HarnessRunSpec,
    request: ProviderRunRequest,
    created_at: datetime,
    status: ProviderRunStatus,
    response: dict,
    metadata: dict,
    provider_error: Exception | None = None,
    completed_at: datetime | None = None,
) -> ProviderRunRecord:
    """Build one provider run ledger record."""
    error_kind = classify_provider_error(provider_error) if provider_error else None
    provider_profile_id = _provider_profile_id(provider)
    provider_session_id = _provider_session_id(provider)
    provider_metadata = dict(metadata)
    if provider_profile_id:
        provider_metadata["provider_profile_id"] = provider_profile_id
    if provider_session_id:
        provider_metadata["provider_session_id"] = provider_session_id
    quota_status = _provider_quota_status(provider)
    if quota_status:
        provider_metadata["quota_status"] = quota_status
    return ProviderRunRecord(
        id=f"provider-{spec.id}",
        provider=_provider_name(provider),
        provider_profile_id=provider_profile_id,
        provider_session_id=provider_session_id,
        session_id=spec.session_id,
        loop_run_id=spec.loop_run_id,
        iteration_id=spec.iteration_id,
        role=spec.role,
        status=status,
        request=request.model_dump(mode="json"),
        response=response,
        error_kind=error_kind,
        error_message=str(provider_error) if provider_error else None,
        created_at=created_at,
        completed_at=(
            None
            if status is ProviderRunStatus.RUNNING
            else (completed_at or created_at)
        ),
        metadata=provider_metadata,
    )


def _decision_for_provider_signal(result) -> RuntimeDecision | None:
    """Return a scheduler decision for provider handoff or scope signals."""
    response = result.metadata.get("provider_response", {})
    handoff = response.get("handoff_request")
    if handoff is not None:
        return RuntimeDecision(
            decision=LoopDecisionType.HUMAN_HANDOFF,
            stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
            reason=str(handoff.get("reason", "Provider requested human handoff.")),
        )
    scope_change = response.get("scope_change")
    if scope_change is not None:
        summary = str(scope_change.get("summary", "Provider suggested a scope change."))
        return RuntimeDecision(
            decision=LoopDecisionType.HUMAN_HANDOFF,
            stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
            reason=f"Scope change suggested: {summary}",
        )
    return None


def _provider_response_payload(result) -> dict:
    """Return the provider response payload persisted in the provider ledger."""
    response = result.metadata.get("provider_response")
    if response is not None:
        return response
    return {
        "status": "succeeded",
        "output": result.output,
        "evidence_refs": [evidence.id for evidence in result.evidence_refs],
    }


def _provider_stop_metadata(result, provider_error: Exception | None) -> dict[str, str]:
    """Return durable actor and reason metadata for provider stop paths."""
    if provider_error is not None:
        kind = classify_provider_error(provider_error).value
        if kind == "cancelled":
            return {
                "stopped_by": "USER",
                "stop_reason": "USER_INTERRUPTED",
                "error_message": redact_error(str(provider_error)),
            }
        if kind == "timeout":
            return {
                "stopped_by": "SYSTEM",
                "stop_reason": "TIMEOUT",
                "error_message": redact_error(str(provider_error)),
            }
        return {
            "stopped_by": "PROVIDER",
            "stop_reason": "PROVIDER_ERROR",
            "error_message": redact_error(str(provider_error)),
        }
    error_kind = str(result.metadata.get("error_kind", "")) if result is not None else ""
    if result is not None and result.status is HarnessStatus.FAILED:
        return {
            "stopped_by": "PROVIDER",
            "stop_reason": "PROVIDER_ERROR",
            "error_kind": error_kind,
            "error_message": redact_error(result.metadata.get("error_message")),
        }
    return {}


async def _execute_step(
    ctx: LoopExecutionContext,
    state: LoopExecutionState,
    step: CompiledLoopStep,
) -> StepOutcome:
    """Execute one compiled step through its declared executor."""
    if step.executor is StepExecutorType.HUMAN_GATE:
        return _execute_human_gate_step(ctx, state, step)
    if step.executor is StepExecutorType.VERIFIER:
        return _execute_verifier_step(ctx, state, step)
    return await _execute_provider_step(ctx, state, step)


def _execute_human_gate_step(
    ctx: LoopExecutionContext,
    state: LoopExecutionState,
    step: CompiledLoopStep,
) -> StepOutcome:
    """Pause the loop for explicit user confirmation of delivery."""
    connection = ctx.connection
    state.run_sequence += 1
    sequence = state.run_sequence
    now = _timestamp(ctx.created_at)
    task_id = scoped_task_id(ctx.loop_run.id, step.task_id)
    iteration = LoopIterationRecord(
        id=scoped_iteration_id(ctx.loop_run.id, sequence, step.step_type),
        loop_run_id=ctx.loop_run.id,
        session_id=ctx.session.id,
        task_id=task_id,
        sequence=sequence,
        step_type=step.step_type,
        role=step.role,
        status=HarnessStatus.SUCCEEDED,
        started_at=now,
        completed_at=now,
    )
    insert_loop_iteration(connection, iteration)
    summary = (
        ctx.goal_contract.summary if ctx.goal_contract is not None else step.task_title
    )
    runtime_decision = RuntimeDecision(
        decision=LoopDecisionType.HUMAN_HANDOFF,
        stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
        reason="Awaiting user confirmation of delivery.",
    )
    decision = LoopDecisionRecord(
        id=f"{ctx.loop_run.id}-decision-{sequence:03d}-{step.step_type.value}",
        loop_run_id=ctx.loop_run.id,
        iteration_id=iteration.id,
        decision=runtime_decision.decision,
        stop_condition=runtime_decision.stop_condition,
        reason=runtime_decision.reason,
        created_at=now,
        metadata={
            "pause_question": f"Confirm delivery: {summary}?",
            "pause_requested_input": (
                "Reply /resume yes to confirm, or /resume <notes> to request changes."
            ),
            "pause_resume_mode": "confirm_gate",
        },
    )
    insert_loop_decision(connection, decision)
    write_step_events(connection, ctx.session.id, task_id, iteration.id, step.step_type, now)
    return StepOutcome(
        runtime_decision=runtime_decision,
        retry_step=None,
        iteration=iteration,
        decision_record=decision,
        completed_at=now,
    )


def _has_implementation_evidence(state: LoopExecutionState) -> bool:
    """Return whether a writer has already produced evidence in this loop.

    True once the loop owns the workspace (across retries and resumes), so the
    clean-tree guard is skipped for subsequent writer dispatches.
    """
    return state.workspace_owned or any(
        evidence.kind is EvidenceKind.IMPLEMENTATION for evidence in state.evidence_refs
    )


def _verification_commands(
    state: LoopExecutionState, step: CompiledLoopStep, project_root: Path
) -> list[list[str]]:
    """Resolve verification commands from step metadata or writer evidence."""
    explicit = step.metadata.get("verification_commands")
    if isinstance(explicit, list) and explicit:
        return [
            [str(part) for part in argv]
            for argv in explicit
            if isinstance(argv, list) and argv
        ]

    implementations = [
        evidence
        for evidence in state.evidence_refs
        if evidence.kind is EvidenceKind.IMPLEMENTATION
    ]
    if implementations:
        commands = implementations[-1].metadata.get("test_commands")
        if isinstance(commands, list):
            return [
                [str(part) for part in argv]
                for argv in commands
                if isinstance(argv, list) and argv
            ]
    return discover_verification_commands(project_root)


def _execute_verifier_step(
    ctx: LoopExecutionContext,
    state: LoopExecutionState,
    step: CompiledLoopStep,
) -> StepOutcome:
    """Run deterministic verification and gate the loop on machine truth."""
    connection = ctx.connection
    state.run_sequence += 1
    sequence = state.run_sequence
    started_at = _timestamp(ctx.created_at)
    task_id = scoped_task_id(ctx.loop_run.id, step.task_id)
    task = ctx.tasks_by_id[task_id]
    iteration = LoopIterationRecord(
        id=scoped_iteration_id(ctx.loop_run.id, sequence, step.step_type),
        loop_run_id=ctx.loop_run.id,
        session_id=ctx.session.id,
        task_id=task_id,
        sequence=sequence,
        step_type=step.step_type,
        role=step.role,
        status=HarnessStatus.RUNNING,
        started_at=started_at,
        completed_at=None,
    )
    insert_loop_iteration(connection, iteration)

    spec = VerificationSpec(
        project_root=Path(ctx.session.project_root),
        commands=_verification_commands(state, step, Path(ctx.session.project_root)),
    )
    verification = run_verification(spec)
    completed_at = _timestamp(ctx.created_at)
    evidence = build_validation_evidence(
        verification,
        spec,
        session_id=ctx.session.id,
        loop_run_id=ctx.loop_run.id,
        iteration_id=iteration.id,
        created_at=completed_at,
    )
    insert_evidence_ref(connection, evidence)
    state.evidence_refs.append(evidence)

    result = HarnessRunResult(
        spec_id=iteration.id,
        status=HarnessStatus.SUCCEEDED,
        role=step.role,
        step_type=LoopStepType.VALIDATE,
        evidence_refs=[evidence],
        output={
            "passed": verification.passed,
            "summary": evidence.summary,
            "checks": [" ".join(command.argv) for command in verification.results],
        },
    )
    if not spec.commands:
        runtime_decision = RuntimeDecision(
            decision=LoopDecisionType.HUMAN_HANDOFF,
            stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
            reason=(
                "No verification commands were found (no tests, pyproject pytest/ruff, "
                "or package.json test/lint). Add tests or set the step's "
                "verification_commands, then resume; Curator will not claim unverified success."
            ),
        )
    else:
        runtime_decision = decide_runtime(step, result, role_contracts=ctx.role_contracts)

    retry_step: CompiledLoopStep | None = None
    if runtime_decision.decision in _RETRY_DECISIONS:
        retry_step = _retry_target_step(ctx.plan, runtime_decision, step)
        attempts = state.retry_counts.get(retry_step.task_id, 0)
        if state.run_sequence + 2 > MAX_ITERATIONS:
            runtime_decision = _max_iterations_decision()
            retry_step = None
        elif attempts >= _max_retries_for_step(retry_step):
            runtime_decision = _paused_after_repeated_failure_decision()
            retry_step = None
        else:
            state.retry_counts[retry_step.task_id] = attempts + 1

    iteration = iteration.model_copy(
        update={"status": HarnessStatus.SUCCEEDED, "completed_at": completed_at}
    )
    decision = LoopDecisionRecord(
        id=f"{ctx.loop_run.id}-decision-{sequence:03d}-{step.step_type.value}",
        loop_run_id=ctx.loop_run.id,
        iteration_id=iteration.id,
        decision=runtime_decision.decision,
        stop_condition=runtime_decision.stop_condition,
        reason=runtime_decision.reason,
        created_at=completed_at,
    )
    insert_loop_iteration(connection, iteration)
    insert_loop_decision(connection, decision)
    record_decision_memory(
        connection,
        decision=decision,
        iteration=iteration,
        evidence_refs=state.evidence_refs,
        scope=str(ctx.session.project_root),
    )
    insert_task(
        connection,
        task.model_copy(
            update={
                "status": (
                    TaskStatus.FAILED
                    if runtime_decision.decision is LoopDecisionType.STOP_FAILED
                    else TaskStatus.DONE
                ),
                "updated_at": completed_at,
            }
        ),
    )
    write_step_events(
        connection, ctx.session.id, task_id, iteration.id, step.step_type, completed_at
    )
    write_step_message(
        connection,
        ctx.session.id,
        task_id,
        iteration.id,
        step.step_type,
        step.role,
        evidence.summary,
        completed_at,
    )
    return StepOutcome(
        runtime_decision=runtime_decision,
        retry_step=retry_step,
        iteration=iteration,
        decision_record=decision,
        completed_at=completed_at,
    )


async def _execute_provider_step(
    ctx: LoopExecutionContext,
    state: LoopExecutionState,
    step: CompiledLoopStep,
) -> StepOutcome:
    """Execute one provider-backed step, persist its ledger rows, and decide."""
    connection = ctx.connection
    step_type = step.step_type
    state.run_sequence += 1
    sequence = state.run_sequence
    step_started_at = _timestamp(ctx.created_at)
    is_retry_attempt = step.task_id in state.retry_task_ids
    state.retry_task_ids.discard(step.task_id)
    task_id = scoped_task_id(ctx.loop_run.id, step.task_id)
    task = ctx.tasks_by_id[task_id]
    spec = HarnessRunSpec(
        id=scoped_harness_id(ctx.loop_run.id, sequence, step_type),
        session_id=ctx.session.id,
        loop_run_id=ctx.loop_run.id,
        iteration_id=scoped_iteration_id(ctx.loop_run.id, sequence, step_type),
        role=step.role,
        step_type=step_type,
        task_id=task_id,
        context_refs=_context_refs_for_step(
            step, state.evidence_refs, include_latest_validation=is_retry_attempt
        ),
        guide_refs=ctx.plan.guide_refs,
    )
    iteration = LoopIterationRecord(
        id=spec.iteration_id,
        loop_run_id=ctx.loop_run.id,
        session_id=ctx.session.id,
        task_id=task_id,
        sequence=sequence,
        step_type=step_type,
        role=spec.role,
        status=HarnessStatus.RUNNING,
        started_at=step_started_at,
        completed_at=None,
    )
    insert_loop_iteration(connection, iteration)
    context_package = build_context_package(
        connection,
        session_id=ctx.session.id,
        loop_run_id=ctx.loop_run.id,
        iteration_id=iteration.id,
        role=spec.role,
        task_id=task_id,
        project_root=ctx.session.project_root,
        goal_contract=ctx.goal_contract,
    )
    # The provider must see the same request the ledger records, including
    # the context package reference — no divergent spec copies.
    spec = spec.model_copy(
        update={"metadata": {**spec.metadata, "context_package_id": context_package.id}}
    )
    provider_request = ProviderRunRequest.from_context_package(spec, context_package)
    recorder = _ledger_event_recorder(ctx, spec, task_id)
    provider_error = None
    result = None
    provider_identity = None
    try:
        # Enforce a clean workspace only on the loop's very first writer
        # dispatch. Retries and resumes legitimately build on the writer's own
        # prior (uncommitted) output, so the guard must not block them.
        if step.slot == "writer" and not _has_implementation_evidence(state):
            require_clean_baseline(capture_baseline(ctx.session.project_root))
        driver = ctx.driver_for_step(step)
        provider_identity = driver
        insert_provider_run(
            connection,
            _provider_run_record(
                provider_identity,
                spec,
                provider_request,
                step_started_at,
                ProviderRunStatus.RUNNING,
                {"status": "running"},
                {"scheduler_decision": "pending"},
            ),
        )
        result = await run_harness_async(
            spec,
            driver,
            provider_request,
            created_at=step_started_at,
            on_event=recorder,
        )
        runtime_decision = _decision_for_provider_signal(result) or decide_runtime(
            step, result, role_contracts=ctx.role_contracts
        )
    except Exception as error:
        provider_error = error
        pause_reason = _pause_reason_for_provider_error(error)
        if pause_reason is None:
            runtime_decision = decide_runtime(step, None, provider_error=error)
        else:
            runtime_decision = RuntimeDecision(
                decision=LoopDecisionType.HUMAN_HANDOFF,
                stop_condition=StopCondition.HUMAN_HANDOFF_REQUESTED,
                reason=pause_reason,
            )

    retry_step: CompiledLoopStep | None = None
    if runtime_decision.decision in _RETRY_DECISIONS:
        retry_step = _retry_target_step(ctx.plan, runtime_decision, step)
        attempts = state.retry_counts.get(retry_step.task_id, 0)
        # A retry schedules at least two more iterations (the retried step
        # plus re-running the current step), so budget both up front.
        if state.run_sequence + 2 > MAX_ITERATIONS:
            runtime_decision = _max_iterations_decision()
            retry_step = None
        elif attempts >= _max_retries_for_step(retry_step):
            runtime_decision = _paused_after_repeated_failure_decision()
            retry_step = None
        else:
            state.retry_counts[retry_step.task_id] = attempts + 1

    step_completed_at = _timestamp(ctx.created_at)
    provider_stop_metadata = _provider_stop_metadata(result, provider_error)
    iteration = iteration.model_copy(
        update={
            "status": (
                HarnessStatus.FAILED
                if provider_error or (result is not None and result.status is HarnessStatus.FAILED)
                else HarnessStatus.SUCCEEDED
            ),
            "completed_at": step_completed_at,
            "metadata": provider_stop_metadata,
        }
    )
    decision = LoopDecisionRecord(
        id=f"{ctx.loop_run.id}-decision-{sequence:03d}-{step_type.value}",
        loop_run_id=ctx.loop_run.id,
        iteration_id=iteration.id,
        decision=runtime_decision.decision,
        stop_condition=runtime_decision.stop_condition,
        reason=runtime_decision.reason,
        created_at=step_completed_at,
        metadata=provider_stop_metadata,
    )

    insert_loop_iteration(connection, iteration)
    provider_failed = provider_error is not None or (
        result is not None and result.status is HarnessStatus.FAILED
    )
    if provider_identity is not None:
        provider_record = _provider_run_record(
            provider_identity,
            spec,
            provider_request,
            step_completed_at,
            ProviderRunStatus.FAILED if provider_failed else ProviderRunStatus.SUCCEEDED,
            {"status": "failed" if provider_failed else "succeeded"}
            if result is None
            else _provider_response_payload(result),
            {"scheduler_decision": runtime_decision.decision.value, **provider_stop_metadata},
            provider_error,
        )
        if result is not None and result.status is HarnessStatus.FAILED:
            raw_kind = result.metadata.get("error_kind")
            provider_record = provider_record.model_copy(
                update={
                    "error_kind": (
                        ProviderErrorKind(raw_kind) if raw_kind in {kind.value for kind in ProviderErrorKind} else None
                    ),
                    "error_message": redact_error(result.metadata.get("error_message")),
                }
            )
        insert_provider_run(
            connection,
            provider_record,
        )
    if result is not None:
        for evidence in result.evidence_refs:
            insert_evidence_ref(connection, evidence)
            state.evidence_refs.append(evidence)
    insert_loop_decision(connection, decision)
    record_decision_memory(
        connection,
        decision=decision,
        iteration=iteration,
        evidence_refs=state.evidence_refs,
        scope=str(ctx.session.project_root),
    )
    insert_task(
        connection,
        task.model_copy(
            update={
                "status": (
                    TaskStatus.FAILED
                    if runtime_decision.decision is LoopDecisionType.STOP_FAILED
                    else TaskStatus.DONE
                ),
                "updated_at": step_completed_at,
            }
        ),
    )
    write_step_events(
        connection, ctx.session.id, task_id, iteration.id, step_type, step_completed_at
    )
    if result is not None:
        write_step_message(
            connection,
            ctx.session.id,
            task_id,
            iteration.id,
            step_type,
            spec.role,
            str(result.output.get("summary", "")),
            step_completed_at,
        )

    return StepOutcome(
        runtime_decision=runtime_decision,
        retry_step=retry_step,
        iteration=iteration,
        decision_record=decision,
        completed_at=step_completed_at,
    )


async def _run_steps(ctx: LoopExecutionContext, state: LoopExecutionState) -> None:
    """Run pending steps until the loop stops, pauses, or completes."""
    connection = ctx.connection
    if ctx.cancellation is not None:
        ctx.cancellation.bind()
    while state.pending_steps:
        if ctx.cancellation is not None:
            ctx.cancellation.raise_if_cancelled()
        step = state.pending_steps.pop(0)
        outcome = await _execute_step(ctx, state, step)
        decision_type = outcome.runtime_decision.decision

        if decision_type is LoopDecisionType.STOP_FAILED:
            write_loop_completion(connection, ctx.loop_run, LoopStatus.FAILED, outcome.completed_at)
            return

        if decision_type is LoopDecisionType.HUMAN_HANDOFF:
            with transaction(connection):
                pause = _pause_record_for_decision(
                    ctx.loop_run.id, outcome.iteration, outcome.decision_record
                )
                pause = pause.model_copy(
                    update={
                        "metadata": {
                            **pause.metadata,
                            "workspace_owned": _has_implementation_evidence(state),
                        }
                    }
                )
                insert_pause_record(
                    connection,
                    pause,
                )
                write_loop_pause(connection, ctx.loop_run, outcome.completed_at)
            return

        if decision_type in _RETRY_DECISIONS and outcome.retry_step is not None:
            state.pending_steps.insert(0, step)
            state.pending_steps.insert(0, outcome.retry_step)
            state.retry_task_ids.add(outcome.retry_step.task_id)
            continue

        if decision_type is LoopDecisionType.STOP_DONE:
            write_loop_completion(connection, ctx.loop_run, LoopStatus.DONE, outcome.completed_at)
            return

        if decision_type in _ADVANCE_DECISIONS:
            continue

        raise ValueError(f"Unhandled loop decision: {decision_type.value}")

    write_loop_completion(connection, ctx.loop_run, LoopStatus.DONE, _timestamp(ctx.created_at))


async def run_workflow_async(
    connection: sqlite3.Connection,
    session_id: str,
    provider: Provider | None = None,
    created_at: datetime | None = None,
    compiled_plan: CompiledLoopPlan | None = None,
    role_contracts: dict[str, RoleContract] | None = None,
    goal_contract: GoalContract | None = None,
    on_event: ProviderEventCallback | None = None,
    driver_resolver: DriverResolver | None = None,
    cancellation: CancellationToken | None = None,
) -> None:
    """Run the compiled workflow asynchronously and persist its loop ledger."""
    loop_run = load_loop_runs_for_session(connection, session_id)[-1]
    session = load_session(connection, session_id)
    if session is None:
        raise ValueError(f"Unknown session: {session_id}")
    plan = (
        compiled_plan
        or load_compiled_plan_for_run(loop_run)
        or compile_coding_delivery_plan(
            session_id=session_id,
            contract_id=loop_run.contract_id,
            role_contracts=role_contracts,
        )
    )
    ctx = LoopExecutionContext(
        connection=connection,
        session=session,
        loop_run=loop_run,
        plan=plan,
        provider=provider,
        driver=driver_for_provider(provider) if provider is not None else None,
        tasks_by_id={task.id: task for task in load_tasks_for_session(connection, session_id)},
        role_contracts=role_contracts,
        goal_contract=goal_contract,
        created_at=created_at,
        on_event=on_event,
        driver_resolver=driver_resolver,
        cancellation=cancellation,
    )
    state = LoopExecutionState(pending_steps=list(plan.steps))
    await _run_steps(ctx, state)


def run_workflow(
    connection: sqlite3.Connection,
    session_id: str,
    provider: Provider | None = None,
    created_at: datetime | None = None,
    compiled_plan: CompiledLoopPlan | None = None,
    role_contracts: dict[str, RoleContract] | None = None,
    goal_contract: GoalContract | None = None,
    on_event: ProviderEventCallback | None = None,
    driver_resolver: DriverResolver | None = None,
    cancellation: CancellationToken | None = None,
) -> None:
    """Run the compiled workflow synchronously (CLI/tests entry point)."""
    try:
        asyncio.run(
            run_workflow_async(
                connection,
                session_id,
                provider,
                created_at=created_at,
                compiled_plan=compiled_plan,
                role_contracts=role_contracts,
                goal_contract=goal_contract,
                on_event=on_event,
                driver_resolver=driver_resolver,
                cancellation=cancellation,
            )
        )
    except asyncio.CancelledError:
        from curator.scheduler.recovery import reconcile

        session = load_session(connection, session_id)
        if session is not None:
            reconcile(connection, session.project_root)

"""Compile role-aware loop templates into scheduler-ready execution plans."""

from collections.abc import Iterable

from curator.core.enums import (
    EvidenceKind,
    LoopDecisionType,
    LoopStepType,
    RoleName,
    StepExecutorType,
    StopCondition,
)
from curator.core.schema import (
    CompiledLoopPlan,
    CompiledLoopStep,
    RoleContract,
    RoleSelection,
)
from curator.loops.templates import (
    coding_delivery_loop,
    role_for_step,
    single_writer_loop,
    template_requires_evidence,
)
from curator.roles.registry import default_role_contracts, get_default_role_contract
from curator.roles.selection import select_role_candidates

_TASK_IDS = {
    LoopStepType.PLAN: "task-001-plan",
    LoopStepType.IMPLEMENT: "task-002-implement",
    LoopStepType.VALIDATE: "task-003-validate",
    LoopStepType.CONFIRM: "task-004-confirm",
}

_TASK_TITLES = {
    LoopStepType.PLAN: "Plan coding delivery",
    LoopStepType.IMPLEMENT: "Implement coding delivery",
    LoopStepType.VALIDATE: "Validate coding delivery",
    LoopStepType.CONFIRM: "Confirm coding delivery",
}

_SUCCESS_DECISIONS = {
    LoopStepType.PLAN: LoopDecisionType.CONTINUE_TO_ENGINEER,
    LoopStepType.IMPLEMENT: LoopDecisionType.CONTINUE_TO_QA,
    LoopStepType.VALIDATE: LoopDecisionType.CONTINUE_TO_PM,
    LoopStepType.CONFIRM: LoopDecisionType.STOP_DONE,
}

_EVIDENCE_ORDER = [
    EvidenceKind.PLAN,
    EvidenceKind.IMPLEMENTATION,
    EvidenceKind.VALIDATION,
    EvidenceKind.REVIEW,
    EvidenceKind.PM_CONFIRMATION,
    EvidenceKind.ARTIFACT,
    EvidenceKind.LOG,
]


def _required_evidence_for_step(step_type: LoopStepType) -> list[EvidenceKind]:
    """Return required evidence kinds for one default coding loop step."""
    template = coding_delivery_loop()
    return [
        evidence_kind
        for evidence_kind in _EVIDENCE_ORDER
        if template_requires_evidence(template, step_type, evidence_kind)
    ]


def _compiled_step(
    sequence: int,
    step_type: LoopStepType,
    role_contracts: dict[str, RoleContract],
) -> CompiledLoopStep:
    """Return one compiled scheduler step for the default coding loop."""
    template = coding_delivery_loop()
    decision = _SUCCESS_DECISIONS[step_type]
    role = role_for_step(template, step_type)
    role_contract = role_contracts.get(role.value, get_default_role_contract(role))
    return CompiledLoopStep(
        id=f"compiled-step-{sequence:03d}-{step_type.value}",
        role_id=role_contract.id,
        task_id=_TASK_IDS[step_type],
        task_title=_TASK_TITLES[step_type],
        sequence=sequence,
        step_type=step_type,
        role=role,
        required_evidence_kinds=_required_evidence_for_step(step_type),
        decision_on_success=decision,
        stop_condition_on_success=(
            StopCondition.DONE_CRITERIA_MET
            if decision is LoopDecisionType.STOP_DONE
            else None
        ),
        metadata={
            "role_display_name": role_contract.display_name,
            "role_capability_tags": role_contract.capability_tags,
            "role_when_to_involve": role_contract.when_to_involve,
        },
    )


def _reviewer_task_id(role_id: str, sequence: int) -> str:
    """Return a stable task id for a selected reviewer role."""
    return f"task-{sequence:03d}-{role_id.replace('_', '-')}"


def _reviewer_step(
    sequence: int,
    contract: RoleContract,
    selection: RoleSelection,
) -> CompiledLoopStep:
    """Return one compiled review step for a selected non-core role."""
    return CompiledLoopStep(
        id=f"compiled-step-{sequence:03d}-{contract.id}",
        role_id=contract.id,
        task_id=_reviewer_task_id(contract.id, sequence),
        task_title=f"{contract.display_name} review",
        sequence=sequence,
        step_type=LoopStepType.VALIDATE,
        role=RoleName.QA,
        required_evidence_kinds=[
            EvidenceKind.PLAN,
            EvidenceKind.IMPLEMENTATION,
        ],
        decision_on_success=LoopDecisionType.CONTINUE_TO_QA,
        metadata={
            "role_display_name": contract.display_name,
            "role_capability_tags": contract.capability_tags,
            "role_when_to_involve": contract.when_to_involve,
            "selection_matched_signals": selection.matched_signals,
            "selection_reason": selection.reason,
            "selection_score": selection.score,
        },
    )


def _renumber_steps(steps: list[CompiledLoopStep]) -> list[CompiledLoopStep]:
    """Return compiled steps with contiguous sequence-derived identifiers."""
    renumbered = []
    for sequence, step in enumerate(steps, start=1):
        if step.role_id not in {"pm", "engineer", "qa"}:
            renumbered.append(
                step.model_copy(
                    update={
                        "sequence": sequence,
                        "id": f"compiled-step-{sequence:03d}-{step.role_id}",
                        "task_id": _reviewer_task_id(step.role_id, sequence),
                    }
                )
            )
            continue

        renumbered.append(step.model_copy(update={"sequence": sequence}))

    return renumbered


_SINGLE_WRITER_TASKS = {
    LoopStepType.IMPLEMENT: ("task-001-write", "Implement the goal"),
    LoopStepType.VALIDATE: ("task-002-verify", "Verify the implementation"),
    LoopStepType.REVIEW: ("task-003-review", "Review the change with fresh context"),
    LoopStepType.CONFIRM: ("task-004-confirm", "Confirm delivery"),
}

_SINGLE_WRITER_EXECUTORS = {
    LoopStepType.IMPLEMENT: StepExecutorType.PROVIDER,
    LoopStepType.VALIDATE: StepExecutorType.VERIFIER,
    LoopStepType.REVIEW: StepExecutorType.PROVIDER,
    LoopStepType.CONFIRM: StepExecutorType.HUMAN_GATE,
}

_SINGLE_WRITER_SLOTS = {
    LoopStepType.IMPLEMENT: "writer",
    LoopStepType.REVIEW: "reviewer",
}


def compile_single_writer_plan(
    session_id: str,
    contract_id: str,
    role_contracts: dict[str, RoleContract] | None = None,
    task_signals: Iterable[str] | None = None,
) -> CompiledLoopPlan:
    """Compile the single-writer template into an executable plan.

    One writer run implements, a deterministic verifier gates the loop exit,
    a fresh-context reviewer assesses the artifacts, and a human gate confirms.
    """
    _ = task_signals
    template = single_writer_loop()
    contracts = role_contracts or default_role_contracts()
    steps: list[CompiledLoopStep] = []
    writer_step_id = "compiled-step-001-implement"
    for sequence, step_type in enumerate(template.steps, start=1):
        role = role_for_step(template, step_type)
        role_contract = contracts.get(role.value, get_default_role_contract(role))
        task_id, task_title = _SINGLE_WRITER_TASKS[step_type]
        is_confirm = step_type is LoopStepType.CONFIRM
        steps.append(
            CompiledLoopStep(
                id=f"compiled-step-{sequence:03d}-{step_type.value}",
                role_id=role_contract.id,
                task_id=task_id,
                task_title=task_title,
                sequence=sequence,
                step_type=step_type,
                role=role,
                executor=_SINGLE_WRITER_EXECUTORS[step_type],
                slot=_SINGLE_WRITER_SLOTS.get(step_type),
                max_retries=2 if step_type is LoopStepType.IMPLEMENT else 1,
                required_evidence_kinds=[
                    evidence_kind
                    for evidence_kind in _EVIDENCE_ORDER
                    if template_requires_evidence(template, step_type, evidence_kind)
                ],
                decision_on_success=(
                    LoopDecisionType.STOP_DONE if is_confirm else LoopDecisionType.CONTINUE
                ),
                stop_condition_on_success=(
                    StopCondition.DONE_CRITERIA_MET if is_confirm else None
                ),
                metadata={
                    "role_display_name": role_contract.display_name,
                    "retry_target_step_id": writer_step_id
                    if step_type is LoopStepType.VALIDATE
                    else None,
                },
            )
        )

    return CompiledLoopPlan(
        id=f"compiled-{contract_id}",
        session_id=session_id,
        contract_id=contract_id,
        template_id=template.id,
        guide_refs=template.guide_refs,
        steps=steps,
    )


def compile_coding_delivery_plan(
    session_id: str,
    contract_id: str,
    role_contracts: dict[str, RoleContract] | None = None,
    task_signals: Iterable[str] | None = None,
) -> CompiledLoopPlan:
    """Compile the Phase 0 coding delivery template into an executable plan."""
    template = coding_delivery_loop()
    contracts = role_contracts or default_role_contracts()
    selected_reviewers = select_role_candidates(
        contracts,
        task_signals or [],
        excluded_role_ids={"pm", "engineer", "qa"},
    )
    base_steps = [
        _compiled_step(sequence, step_type, contracts)
        for sequence, step_type in enumerate(template.steps, start=1)
    ]
    reviewer_steps = [
        _reviewer_step(3 + index, contracts[selection.role_id], selection)
        for index, selection in enumerate(selected_reviewers)
    ]
    steps = _renumber_steps([*base_steps[:2], *reviewer_steps, *base_steps[2:]])

    return CompiledLoopPlan(
        id=f"compiled-{contract_id}",
        session_id=session_id,
        contract_id=contract_id,
        template_id=template.id,
        guide_refs=template.guide_refs,
        steps=steps,
    )

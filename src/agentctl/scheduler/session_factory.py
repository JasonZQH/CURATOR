"""Build scheduler session skeleton records."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agentctl.core.enums import LoopStatus, SessionMode, TaskStatus
from agentctl.core.schema import (
    CompiledLoopPlan,
    CompiledLoopStep,
    LoopRunRecord,
    RoleSelectionRecord,
    SessionRecord,
    TaskRecord,
)
from agentctl.scheduler.ids import new_loop_run_id, scoped_task_id


@dataclass(frozen=True)
class WorkflowSessionSkeleton:
    """Group records required to initialize one workflow session."""

    session: SessionRecord
    loop_run: LoopRunRecord
    tasks: list[TaskRecord]
    role_selections: list[RoleSelectionRecord]


def role_selection_for_step(
    step: CompiledLoopStep,
    session_id: str,
    loop_run_id: str,
    created_at: datetime,
) -> RoleSelectionRecord | None:
    """Return a role selection record when a compiled step was dynamically selected."""
    reason = step.metadata.get("selection_reason")
    if not reason:
        return None

    return RoleSelectionRecord(
        id=f"{loop_run_id}-role-selection-{step.sequence:03d}-{step.role_id}",
        session_id=session_id,
        loop_run_id=loop_run_id,
        role_id=step.role_id,
        display_name=str(step.metadata["role_display_name"]),
        matched_signals=list(step.metadata.get("selection_matched_signals", [])),
        score=int(step.metadata.get("selection_score", 0)),
        reason=str(reason),
        created_at=created_at,
        metadata={"compiled_step_id": step.id},
    )


def build_workflow_session_records(
    project_root: Path | str,
    created_at: datetime,
    compiled_plan: CompiledLoopPlan,
) -> WorkflowSessionSkeleton:
    """Build session, task, loop, and role-selection records without writing them."""
    session = SessionRecord(
        id=compiled_plan.session_id,
        project_root=Path(project_root),
        mode=SessionMode.PLAN_FIRST,
        created_at=created_at,
        updated_at=created_at,
    )
    loop_run = LoopRunRecord(
        id=new_loop_run_id(session.id),
        session_id=session.id,
        contract_id=compiled_plan.contract_id,
        template_id=compiled_plan.template_id,
        status=LoopStatus.RUNNING,
        created_at=created_at,
        updated_at=created_at,
        # Resume must replay the exact plan this run started with, so the
        # compiled plan is persisted instead of recompiled from templates.
        metadata={"compiled_plan": compiled_plan.model_dump(mode="json")},
    )
    tasks = [
        TaskRecord(
            id=scoped_task_id(loop_run.id, step.task_id),
            session_id=session.id,
            role=step.role,
            status=TaskStatus.QUEUED,
            title=step.task_title,
            created_at=created_at,
            updated_at=created_at,
            metadata={"role_id": step.role_id},
        )
        for step in compiled_plan.steps
    ]
    role_selections = [
        selection
        for step in compiled_plan.steps
        if (selection := role_selection_for_step(step, session.id, loop_run.id, created_at))
        is not None
    ]
    return WorkflowSessionSkeleton(
        session=session,
        loop_run=loop_run,
        tasks=tasks,
        role_selections=role_selections,
    )

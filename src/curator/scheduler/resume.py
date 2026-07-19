"""Resume a paused loop by replaying its ledger state.

The loop ledger records everything needed to continue: the compiled plan lives
in the loop run metadata, prior evidence and iterations are queryable, and the
pause cursor records how the loop should resume. This module reconstructs the
in-memory execution state from those durable rows and re-enters the scheduler.
"""

import sqlite3
from datetime import UTC, datetime

from curator.core.enums import LoopStatus, LoopStepType, PauseStatus, TaskStatus
from curator.core.schema import GoalContract, MemoryEntryRecord, PauseRecord
from curator.providers.base import Provider
from curator.providers.events import ProviderEventCallback
from curator.providers.driver import driver_for_provider
from curator.scheduler.engine import (
    DriverResolver,
    LoopExecutionContext,
    LoopExecutionState,
    _run_steps,
    load_compiled_plan_for_run,
)
from curator.scheduler.step_writer import write_loop_completion
from curator.scheduler.cancellation import CancellationToken
from curator.state.repositories import (
    insert_loop_run,
    insert_memory_entry,
    insert_pause_record,
    insert_task,
    load_evidence_refs_for_run,
    load_goal_revision,
    load_goal_run_for_loop,
    load_loop_iterations_for_run,
    load_loop_run,
    load_pause_records_for_run,
    load_session,
    load_tasks_for_session,
)
from curator.state.transaction import transaction

_AFFIRMATIVE = {"yes", "y", "confirm", "confirmed", "lgtm", "approve", "approved", "ship it"}


def _affirmative(message: str) -> bool:
    """Return whether a resume message confirms delivery."""
    return message.strip().lower() in _AFFIRMATIVE


def _open_pause(connection: sqlite3.Connection, loop_run_id: str) -> PauseRecord | None:
    """Return the latest open pause cursor for one loop run."""
    open_pauses = [
        pause
        for pause in load_pause_records_for_run(connection, loop_run_id)
        if pause.status is PauseStatus.OPEN
    ]
    return open_pauses[-1] if open_pauses else None


def _goal_contract_for_loop(
    connection: sqlite3.Connection, loop_run_id: str
) -> GoalContract | None:
    """Reconstruct the goal contract bound to one loop run."""
    goal_run = load_goal_run_for_loop(connection, loop_run_id)
    if goal_run is None:
        return None
    revision = load_goal_revision(connection, goal_run.goal_revision_id)
    if revision is None:
        return None
    return GoalContract.model_validate(revision.contract)


def _writer_onward(plan_steps: list) -> list:
    """Return the writer step and everything after it for a re-run."""
    for index, step in enumerate(plan_steps):
        if step.slot == "writer" or step.step_type is LoopStepType.IMPLEMENT:
            return list(plan_steps[index:])
    return list(plan_steps)


def _record_resume_guidance(
    connection: sqlite3.Connection,
    project_root: str,
    pause: PauseRecord,
    message: str,
) -> None:
    """Persist resume guidance as memory so the re-run context carries it."""
    cleaned = message.strip()
    if not cleaned:
        return
    insert_memory_entry(
        connection,
        MemoryEntryRecord(
            id=f"memory-resume-{pause.id}",
            scope=project_root,
            role=None,
            source_ref=pause.id,
            summary=f"User resume guidance: {cleaned}",
            kind="guidance",
            created_at=datetime.now(UTC),
        ),
    )


async def resume_workflow(
    connection: sqlite3.Connection,
    loop_run_id: str,
    message: str,
    provider: Provider | None = None,
    driver_resolver: DriverResolver | None = None,
    created_at: datetime | None = None,
    cancellation: CancellationToken | None = None,
    on_event: ProviderEventCallback | None = None,
) -> bool:
    """Resume a paused loop from the ledger; return whether it resumed.

    An affirmative reply to a confirm gate finalizes the loop as done; any other
    resume re-runs the writer step onward with the guidance carried in context.
    Legacy runs without a persisted plan are refused rather than guessed at.
    """
    loop_run = load_loop_run(connection, loop_run_id)
    if loop_run is None or loop_run.status is not LoopStatus.PAUSED:
        return False

    plan = load_compiled_plan_for_run(loop_run)
    if plan is None:
        return False

    session = load_session(connection, loop_run.session_id)
    if session is None:
        return False

    pause = _open_pause(connection, loop_run_id)
    if pause is None:
        return False

    now = created_at or datetime.now(UTC)
    with transaction(connection):
        insert_pause_record(
            connection,
            pause.model_copy(update={"status": PauseStatus.RESOLVED, "resolved_at": now}),
        )

        if pause.resume_mode == "confirm_gate" and _affirmative(message):
            for task in load_tasks_for_session(connection, session.id):
                if task.id == pause.task_id:
                    insert_task(
                        connection,
                        task.model_copy(update={"status": TaskStatus.DONE, "updated_at": now}),
                    )
                    break
            write_loop_completion(connection, loop_run, LoopStatus.DONE, now)
            return True

        _record_resume_guidance(connection, str(session.project_root), pause, message)
        running = loop_run.model_copy(update={"status": LoopStatus.RUNNING, "updated_at": now})
        insert_loop_run(connection, running)

    state = LoopExecutionState(
        pending_steps=_writer_onward(plan.steps),
        evidence_refs=list(load_evidence_refs_for_run(connection, loop_run_id)),
        run_sequence=len(load_loop_iterations_for_run(connection, loop_run_id)),
        workspace_owned=bool(pause.metadata.get("workspace_owned")),
    )
    ctx = LoopExecutionContext(
        connection=connection,
        session=session,
        loop_run=running,
        plan=plan,
        provider=provider,
        driver=driver_for_provider(provider) if provider is not None else None,
        tasks_by_id={
            task.id: task for task in load_tasks_for_session(connection, session.id)
        },
        role_contracts=None,
        goal_contract=_goal_contract_for_loop(connection, loop_run_id),
        created_at=created_at,
        driver_resolver=driver_resolver,
        cancellation=cancellation,
        on_event=on_event,
    )
    await _run_steps(ctx, state)
    return True


def resume_workflow_sync(
    connection: sqlite3.Connection,
    loop_run_id: str,
    message: str,
    provider: Provider | None = None,
    driver_resolver: DriverResolver | None = None,
    created_at: datetime | None = None,
    cancellation: CancellationToken | None = None,
    on_event: ProviderEventCallback | None = None,
) -> bool:
    """Run resume_workflow synchronously (CLI/shell entry point)."""
    import asyncio

    try:
        return asyncio.run(
            resume_workflow(
                connection,
                loop_run_id,
                message,
                provider=provider,
                driver_resolver=driver_resolver,
                created_at=created_at,
                cancellation=cancellation,
                on_event=on_event,
            )
        )
    except asyncio.CancelledError:
        from curator.scheduler.recovery import reconcile

        reconcile(connection)
        return False

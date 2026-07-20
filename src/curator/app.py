"""Coordinate init, state, scheduler, provider, and TUI services."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from curator.core.enums import GoalStatus, LoopStatus
from curator.core.schema import GoalContract, GoalRunRecord, WorkflowSnapshot
from curator.init.proposal import build_init_proposal, render_init_proposal
from curator.init.wizard import create_curator_state
from curator.providers.base import Provider
from curator.providers.events import ProviderEventCallback
from curator.providers.registry import resolve_provider_for_step
from curator.loops.compiler import compile_single_writer_plan
from curator.scheduler.engine import create_workflow_session, run_workflow
from curator.scheduler.cancellation import CancellationToken
from curator.scheduler.ids import new_session_id
from curator.scheduler.resume import resume_workflow_sync
from curator.scheduler.snapshots import load_workflow_snapshot
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_goal_identity,
    insert_goal_run,
    load_goal_revision,
    load_goal_run_for_loop,
    load_latest_pause_record,
    load_loop_run,
    load_loop_runs_for_session,
    update_goal_status,
)
from curator.runtime.lockfile import project_write_lock
from curator.state.transaction import transaction
from curator.team.roles import load_role_contracts
from curator.tui.workflow_panel import render_workflow_lines


@dataclass(frozen=True)
class InitWriteSummary:
    """Summarize files created or skipped by an approved init run."""

    created_files_count: int
    skipped_files_count: int


def preview_init(project_root: Path | str) -> str:
    """Return the rendered Curator init proposal without writing state."""
    proposal = build_init_proposal(Path(project_root))
    return render_init_proposal(proposal)


def write_init_state(project_root: Path | str) -> InitWriteSummary:
    """Create Curator state and return created and skipped file counts."""
    proposal = build_init_proposal(Path(project_root))
    result = create_curator_state(proposal)
    return InitWriteSummary(
        created_files_count=len(result.created_files),
        skipped_files_count=len(result.skipped_files),
    )


def run_workflow_snapshot(
    project_root: Path | str,
    provider: Provider,
    session_id: str | None = None,
) -> WorkflowSnapshot:
    """Run one explicit-provider workflow and return its workflow snapshot."""
    with project_write_lock(project_root):
        return _run_workflow_snapshot_unlocked(
            project_root, provider, session_id=session_id
        )


def _run_workflow_snapshot_unlocked(
    project_root: Path | str,
    provider: Provider,
    session_id: str | None = None,
) -> WorkflowSnapshot:
    """Run one explicit-provider workflow while the caller owns the lock."""
    root = Path(project_root)
    proposal = build_init_proposal(root)
    role_contract_result = load_role_contracts(proposal.paths)
    role_contracts = role_contract_result.contracts
    connection = connect_database(proposal.paths.database)
    try:
        initialize_database(connection)
        created_session_id = create_workflow_session(
            connection,
            root,
            session_id=session_id,
            role_contracts=role_contracts,
        )
        run_workflow(
            connection,
            created_session_id,
            provider,
            role_contracts=role_contracts,
        )
        return load_workflow_snapshot(connection, created_session_id)
    finally:
        connection.close()


def _goal_status_for_loop(loop_status: LoopStatus) -> GoalStatus:
    """Return the goal status implied by the latest loop status."""
    if loop_status is LoopStatus.DONE:
        return GoalStatus.DONE
    if loop_status is LoopStatus.PAUSED:
        return GoalStatus.PAUSED
    if loop_status is LoopStatus.CANCELLED:
        return GoalStatus.CANCELLED
    if loop_status is LoopStatus.FAILED:
        return GoalStatus.FAILED
    return GoalStatus.RUNNING


def start_goal_loop(
    project_root: Path | str,
    goal_revision_id: str,
    provider: Provider | None = None,
    on_event: ProviderEventCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> WorkflowSnapshot:
    """Start a provider-backed loop from one accepted goal revision."""
    with project_write_lock(project_root):
        return _start_goal_loop_unlocked(
            project_root,
            goal_revision_id,
            provider=provider,
            on_event=on_event,
            cancellation=cancellation,
        )


def _start_goal_loop_unlocked(
    project_root: Path | str,
    goal_revision_id: str,
    provider: Provider | None = None,
    on_event: ProviderEventCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> WorkflowSnapshot:
    """Start one goal loop while the caller owns the project write lock."""
    root = Path(project_root)
    proposal = build_init_proposal(root)
    role_contract_result = load_role_contracts(proposal.paths)
    role_contracts = role_contract_result.contracts
    connection = connect_database(proposal.paths.database)
    now = datetime.now(UTC)
    try:
        initialize_database(connection)
        revision = load_goal_revision(connection, goal_revision_id)
        if revision is None:
            msg = f"Unknown goal revision: {goal_revision_id}"
            raise ValueError(msg)

        goal = GoalContract.model_validate(revision.contract)
        plan = compile_single_writer_plan(
            session_id=new_session_id(),
            contract_id="contract-single-writer",
            role_contracts=role_contracts,
        )
        created_session_id = create_workflow_session(
            connection,
            root,
            compiled_plan=plan,
            role_contracts=role_contracts,
        )
        loop_run = load_loop_runs_for_session(connection, created_session_id)[-1]
        goal_run_id = f"{revision.id}-run-{loop_run.id}"
        with transaction(connection):
            insert_goal_identity(
                connection,
                goal.id,
                goal.source_request,
                goal.summary,
                GoalStatus.RUNNING.value,
                revision.id,
                (goal.created_at or now).isoformat(),
                now.isoformat(),
                goal.metadata,
            )
            insert_goal_run(
                connection,
                GoalRunRecord(
                    id=goal_run_id,
                    goal_id=goal.id,
                    goal_revision_id=revision.id,
                    session_id=created_session_id,
                    loop_run_id=loop_run.id,
                    status=GoalStatus.RUNNING,
                    started_at=now,
                ),
            )
        driver_resolver = None
        if provider is None:
            driver_resolver = lambda step: resolve_provider_for_step(connection, step, root)  # noqa: E731
        run_workflow(
            connection,
            created_session_id,
            provider,
            compiled_plan=plan,
            role_contracts=role_contracts,
            goal_contract=goal,
            on_event=on_event,
            driver_resolver=driver_resolver,
            cancellation=cancellation,
        )
        loop_run = load_loop_runs_for_session(connection, created_session_id)[-1]
        sync_goal_run_status(connection, loop_run.id)
        return load_workflow_snapshot(connection, created_session_id)
    finally:
        connection.close()


def resume_goal_loop(
    project_root: Path | str,
    message: str,
    provider: Provider | None = None,
    on_event: ProviderEventCallback | None = None,
    cancellation: CancellationToken | None = None,
    loop_run_id: str | None = None,
) -> WorkflowSnapshot | None:
    """Resume the latest paused loop from the ledger.

    Returns the refreshed workflow snapshot when a paused loop was resumed, or
    None when there is no resumable paused loop for the project.
    """
    with project_write_lock(project_root):
        return _resume_goal_loop_unlocked(
            project_root,
            message,
            provider=provider,
            on_event=on_event,
            cancellation=cancellation,
            loop_run_id=loop_run_id,
        )


def _resume_goal_loop_unlocked(
    project_root: Path | str,
    message: str,
    provider: Provider | None = None,
    on_event: ProviderEventCallback | None = None,
    cancellation: CancellationToken | None = None,
    loop_run_id: str | None = None,
) -> WorkflowSnapshot | None:
    """Resume one paused loop while the caller owns the project write lock."""
    root = Path(project_root)
    proposal = build_init_proposal(root)
    if not proposal.paths.database.exists():
        return None

    connection = connect_database(proposal.paths.database)
    try:
        initialize_database(connection)
        pause = load_latest_pause_record(connection, loop_run_id)
        if pause is None:
            return None

        driver_resolver = None
        if provider is None:
            driver_resolver = lambda step: resolve_provider_for_step(connection, step, root)  # noqa: E731
        resumed = resume_workflow_sync(
            connection,
            pause.loop_run_id,
            message,
            provider=provider,
            driver_resolver=driver_resolver,
            on_event=on_event,
            cancellation=cancellation,
        )
        if not resumed:
            return None

        sync_goal_run_status(connection, pause.loop_run_id)
        session = load_session_for_loop(connection, pause.loop_run_id)
        if session is None:
            return None
        return load_workflow_snapshot(connection, session)
    finally:
        connection.close()


def sync_goal_run_status(connection, loop_run_id: str) -> None:
    """Sync the goal run and identity status to the loop's current status (start/resume/cancel)."""
    loop_run = load_loop_run(connection, loop_run_id)
    goal_run = load_goal_run_for_loop(connection, loop_run_id)
    if loop_run is None or goal_run is None:
        return
    status = _goal_status_for_loop(loop_run.status)
    insert_goal_run(
        connection,
        goal_run.model_copy(
            update={"status": status, "completed_at": loop_run.completed_at}
        ),
    )
    # Keep the durable goal identity status in step with its latest run so the ledger
    # never leaves a finished goal marked 'running' for a future goal-history reader.
    update_goal_status(
        connection,
        goal_run.goal_id,
        status.value,
        (loop_run.completed_at or datetime.now(UTC)).isoformat(),
    )


def load_session_for_loop(connection, loop_run_id: str) -> str | None:
    """Return the session id owning one loop run."""
    loop_run = load_loop_run(connection, loop_run_id)
    return loop_run.session_id if loop_run is not None else None


def render_workflow(
    project_root: Path | str,
    provider: Provider,
    session_id: str | None = None,
) -> list[str]:
    """Run one explicit-provider workflow and return terminal-friendly lines."""
    snapshot = run_workflow_snapshot(project_root, provider, session_id=session_id)
    return render_workflow_lines(snapshot)

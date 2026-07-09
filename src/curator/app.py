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
)
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
    return GoalStatus.RUNNING


def start_goal_loop(
    project_root: Path | str,
    goal_revision_id: str,
    provider: Provider | None = None,
    on_event: ProviderEventCallback | None = None,
) -> WorkflowSnapshot:
    """Start a provider-backed loop from one accepted goal revision."""
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
        )
        loop_run = load_loop_runs_for_session(connection, created_session_id)[-1]
        goal_status = _goal_status_for_loop(loop_run.status)
        insert_goal_identity(
            connection,
            goal.id,
            goal.source_request,
            goal.summary,
            goal_status.value,
            revision.id,
            (goal.created_at or now).isoformat(),
            now.isoformat(),
            goal.metadata,
        )
        insert_goal_run(
            connection,
            GoalRunRecord(
                id=f"{revision.id}-run-{loop_run.id}",
                goal_id=goal.id,
                goal_revision_id=revision.id,
                session_id=created_session_id,
                loop_run_id=loop_run.id,
                status=goal_status,
                started_at=now,
                completed_at=loop_run.completed_at,
            ),
        )
        return load_workflow_snapshot(connection, created_session_id)
    finally:
        connection.close()


def resume_goal_loop(
    project_root: Path | str,
    message: str,
    provider: Provider | None = None,
) -> WorkflowSnapshot | None:
    """Resume the latest paused loop from the ledger.

    Returns the refreshed workflow snapshot when a paused loop was resumed, or
    None when there is no resumable paused loop for the project.
    """
    root = Path(project_root)
    proposal = build_init_proposal(root)
    if not proposal.paths.database.exists():
        return None

    connection = connect_database(proposal.paths.database)
    try:
        initialize_database(connection)
        pause = load_latest_pause_record(connection)
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
        )
        if not resumed:
            return None

        _sync_goal_run_status(connection, pause.loop_run_id)
        session = load_session_for_loop(connection, pause.loop_run_id)
        if session is None:
            return None
        return load_workflow_snapshot(connection, session)
    finally:
        connection.close()


def _sync_goal_run_status(connection, loop_run_id: str) -> None:
    """Update the goal run status after a resume changes the loop status."""
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

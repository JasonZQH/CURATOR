"""Build workflow snapshots for TUI and future API consumers."""

import sqlite3

from curator.core.schema import WorkflowSnapshot
from curator.state.repositories import (
    load_events_for_session,
    load_evidence_refs_for_run,
    load_loop_decisions_for_run,
    load_loop_iterations_for_run,
    load_loop_runs_for_session,
    load_messages_for_session,
    load_context_packages_for_run,
    load_pause_records_for_run,
    load_provider_runs_for_run,
    load_resume_events_for_pause,
    load_role_selections_for_run,
    load_latest_session,
    load_session,
    load_tasks_for_session,
)


def load_workflow_snapshot(
    connection: sqlite3.Connection,
    session_id: str,
) -> WorkflowSnapshot:
    """Load one complete workflow snapshot for a session."""
    session = load_session(connection, session_id)
    if session is None:
        raise ValueError(f"Unknown session: {session_id}")

    loop_runs = load_loop_runs_for_session(connection, session_id)
    loop_iterations = []
    loop_decisions = []
    evidence_refs = []
    role_selections = []
    pause_records = []
    resume_events = []
    provider_runs = []
    context_packages = []

    for loop_run in loop_runs:
        loop_iterations.extend(load_loop_iterations_for_run(connection, loop_run.id))
        loop_decisions.extend(load_loop_decisions_for_run(connection, loop_run.id))
        evidence_refs.extend(load_evidence_refs_for_run(connection, loop_run.id))
        role_selections.extend(load_role_selections_for_run(connection, loop_run.id))
        pause_records.extend(load_pause_records_for_run(connection, loop_run.id))
        provider_runs.extend(load_provider_runs_for_run(connection, loop_run.id))
        context_packages.extend(load_context_packages_for_run(connection, loop_run.id))

    for pause_record in pause_records:
        resume_events.extend(load_resume_events_for_pause(connection, pause_record.id))

    return WorkflowSnapshot(
        session=session,
        tasks=load_tasks_for_session(connection, session_id),
        messages=load_messages_for_session(connection, session_id),
        events=load_events_for_session(connection, session_id),
        loop_runs=loop_runs,
        loop_iterations=loop_iterations,
        loop_decisions=loop_decisions,
        evidence_refs=evidence_refs,
        role_selections=role_selections,
        pause_records=pause_records,
        resume_events=resume_events,
        provider_runs=provider_runs,
        context_packages=context_packages,
    )


def load_latest_workflow_snapshot(connection: sqlite3.Connection) -> WorkflowSnapshot:
    """Load a workflow snapshot for the latest session."""
    session = load_latest_session(connection)
    if session is None:
        raise ValueError("No sessions have been created.")

    return load_workflow_snapshot(connection, session.id)

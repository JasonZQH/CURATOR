"""Inspect current Curator project state without mutating files."""

import sqlite3
from pathlib import Path

from agentctl.core.paths import build_curator_paths
from agentctl.diagnostics.models import StatusReport
from agentctl.providers.profiles import resolve_runtime_mode
from agentctl.state.db import connect_database
from agentctl.team.roles import load_role_contracts


def _query_one(connection: sqlite3.Connection, query: str) -> sqlite3.Row | None:
    """Return one row for a read-only status query."""
    return connection.execute(query).fetchone()


def _read_status_from_database(project_root: Path, database: Path) -> StatusReport:
    """Read session and decision summary fields from an existing database."""
    connection = connect_database(database)
    try:
        session_count = int(
            _query_one(connection, "select count(*) as count from sessions")["count"]
        )
        last_session = _query_one(
            connection,
            "select id from sessions order by updated_at desc, id desc limit 1",
        )
        last_decision = _query_one(
            connection,
            """
            select decision, stop_condition
            from loop_decisions
            order by created_at desc, id desc
            limit 1
            """,
        )
        try:
            mode = resolve_runtime_mode(connection)
            mode_label = mode.label
        except sqlite3.DatabaseError:
            mode_label = "setup"
    finally:
        connection.close()

    paths = build_curator_paths(project_root)
    contract_result = load_role_contracts(paths)
    next_step = (
        "curator provider add claude-code"
        if mode_label == "setup"
        else "curator"
    )
    return StatusReport(
        project_root=project_root,
        state_dir=paths.curator_dir,
        database=paths.database,
        initialized=True,
        session_count=session_count,
        mode=mode_label,
        last_session_id=last_session["id"] if last_session else None,
        last_decision=last_decision["decision"] if last_decision else None,
        last_stop_condition=last_decision["stop_condition"] if last_decision else None,
        contract_warnings=contract_result.warnings,
        next_step=next_step,
    )


def _uninitialized_status(project_root: Path) -> StatusReport:
    """Return the status summary for a project without Curator state."""
    paths = build_curator_paths(project_root)
    return StatusReport(
        project_root=project_root,
        state_dir=paths.curator_dir,
        database=paths.database,
        initialized=False,
        session_count=0,
        next_step="curator init",
    )


def inspect_project_status(project_root: Path | str) -> StatusReport:
    """Build a read-only status report for a project root."""
    root = Path(project_root)
    paths = build_curator_paths(root)
    if not paths.curator_dir.exists() or not paths.database.exists():
        return _uninitialized_status(root)

    try:
        return _read_status_from_database(root, paths.database)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, KeyError, TypeError):
        return _uninitialized_status(root)

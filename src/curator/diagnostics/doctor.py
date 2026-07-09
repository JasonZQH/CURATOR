"""Inspect local Curator setup health without mutating project state."""

import sqlite3
import sys
from pathlib import Path

from curator import __version__
from curator.core.paths import build_curator_paths
from curator.diagnostics.models import DoctorCheck, DoctorReport
from curator.providers.profiles import resolve_runtime_mode
from curator.state.db import connect_database


def _check_existing_path(path: Path, ok_detail: str, missing_detail: str) -> DoctorCheck:
    """Return an ok or missing check for a filesystem path."""
    if path.exists():
        return DoctorCheck(status="ok", detail=ok_detail)

    return DoctorCheck(status="missing", detail=missing_detail)


def inspect_project_health(project_root: Path | str) -> DoctorReport:
    """Build a read-only doctor report for a project root."""
    root = Path(project_root)
    paths = build_curator_paths(root)
    state_check = _check_existing_path(
        paths.curator_dir,
        "Curator state directory exists.",
        "Run curator init to create local state.",
    )
    database_check = _check_existing_path(
        paths.database,
        "Curator SQLite database exists.",
        "Run curator init to create curator.sqlite.",
    )
    initialized = state_check.status == "ok" and database_check.status == "ok"
    mode = _resolve_mode(paths.database) if initialized else "setup"
    if not initialized:
        next_step = "curator init"
    elif mode == "setup":
        next_step = "curator provider add claude-code"
    else:
        next_step = "curator"

    return DoctorReport(
        project_root=root,
        package_version=__version__,
        python_version=sys.version.split()[0],
        state_dir=paths.curator_dir,
        database=paths.database,
        initialized=initialized,
        recommended_next_step=next_step,
        mode=mode,
        checks={
            "python": DoctorCheck(status="ok", detail=sys.version.split()[0]),
            "package": DoctorCheck(status="ok", detail=f"curator {__version__}"),
            "state": state_check,
            "database": database_check,
        },
    )


def _resolve_mode(database: Path) -> str:
    """Return the runtime mode label for an existing database."""
    try:
        connection = connect_database(database)
        try:
            return resolve_runtime_mode(connection).label
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return "setup"

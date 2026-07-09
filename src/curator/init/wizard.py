"""Drive the init wizard and create approved Curator state."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from curator.core.schema import InitProposal
from curator.runtime.role_pool import ensure_default_role_pool
from curator.state.db import connect_database, initialize_database
from curator.team.memory import write_default_memory
from curator.team.roles import write_default_roles


class InitStateResult(BaseModel):
    """Describe the files created or skipped by an approved init run."""

    model_config = ConfigDict(extra="forbid")

    created_files: list[Path] = Field(default_factory=list)
    skipped_files: list[Path] = Field(default_factory=list)


def _write_state_gitignore(paths) -> Path | None:
    """Write .curator/.gitignore so a project never tracks local Curator state.

    This keeps `curator init` from dirtying the target repo's working tree
    (which would otherwise block the writer's clean-tree guard) and prevents
    users from committing their local ledger.
    """
    gitignore = paths.curator_dir / ".gitignore"
    if gitignore.exists():
        return None
    gitignore.parent.mkdir(parents=True, exist_ok=True)
    gitignore.write_text("# Curator local state — do not commit.\n*\n")
    return gitignore


def create_curator_state(proposal: InitProposal) -> InitStateResult:
    """Create approved Curator files and initialize the SQLite database."""
    paths = proposal.paths
    database_existed = paths.database.exists()

    created_files = [
        *write_default_roles(paths),
        *write_default_memory(paths),
    ]

    state_gitignore = _write_state_gitignore(paths)
    if state_gitignore is not None:
        created_files.append(state_gitignore)

    connection = connect_database(paths.database)
    try:
        initialize_database(connection)
        ensure_default_role_pool(connection)
    finally:
        connection.close()

    if not database_existed:
        created_files.append(paths.database)

    skipped_files = [
        path for path in proposal.proposed_files if path.exists() and path not in created_files
    ]

    return InitStateResult(created_files=created_files, skipped_files=skipped_files)

"""Drive the init wizard and create approved Curator state."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agentctl.core.schema import InitProposal
from agentctl.runtime.role_pool import ensure_default_role_pool
from agentctl.state.db import connect_database, initialize_database
from agentctl.team.memory import write_default_memory
from agentctl.team.roles import write_default_roles


class InitStateResult(BaseModel):
    """Describe the files created or skipped by an approved init run."""

    model_config = ConfigDict(extra="forbid")

    created_files: list[Path] = Field(default_factory=list)
    skipped_files: list[Path] = Field(default_factory=list)


def create_curator_state(proposal: InitProposal) -> InitStateResult:
    """Create approved Curator files and initialize the SQLite database."""
    paths = proposal.paths
    database_existed = paths.database.exists()

    created_files = [
        *write_default_roles(paths),
        *write_default_memory(paths),
    ]

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


create_agentctl_state = create_curator_state

"""Define project-local Curator path models."""

from pathlib import Path

from agentctl.core.enums import RoleName
from agentctl.core.models.base import CuratorModel


def _coerce_role_value(role: RoleName | str) -> str:
    """Return a validated role value for path construction."""
    if isinstance(role, RoleName):
        return role.value

    role_value = str(role)
    if not role_value:
        msg = "Role path value cannot be empty."
        raise ValueError(msg)
    return role_value


class CuratorPaths(CuratorModel):
    """Describe all project-local paths owned by Curator."""

    project_root: Path
    curator_dir: Path
    database: Path
    goals_dir: Path
    team_dir: Path
    roles_dir: Path
    memory_dir: Path
    role_memory_dir: Path
    sessions_dir: Path
    worktrees_dir: Path
    logs_dir: Path

    @property
    def agentctl_dir(self) -> Path:
        """Return the Curator state directory using the legacy alias."""
        return self.curator_dir

    @property
    def db_path(self) -> Path:
        """Return the SQLite database path using the explicit alias."""
        return self.database

    def role_file(self, role: RoleName | str) -> Path:
        """Return the markdown role contract path for a team role."""
        role_value = _coerce_role_value(role)
        return self.roles_dir / role_value / "role.md"

    def goal_file(self, goal_id: str) -> Path:
        """Return the editable YAML draft path for a goal."""
        if not goal_id:
            msg = "Goal id cannot be empty."
            raise ValueError(msg)
        return self.goals_dir / "drafts" / f"{goal_id}.yaml"

    def role_contract_file(self, role: RoleName | str) -> Path:
        """Return the editable YAML role contract path for a team role."""
        role_value = _coerce_role_value(role)
        return self.roles_dir / role_value / "contract.yaml"

    def role_memory_file(self, role: RoleName | str) -> Path:
        """Return the markdown memory path for a team role."""
        role_value = _coerce_role_value(role)
        return self.role_memory_dir / f"{role_value}.md"


AgentctlPaths = CuratorPaths

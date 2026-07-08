"""Build and validate filesystem paths for project-local Curator state."""

from pathlib import Path

from agentctl.core.schema import CuratorPaths


def build_curator_paths(project_root: Path | str) -> CuratorPaths:
    """Build the complete project-local Curator path contract."""
    root = Path(project_root)
    curator_dir = root / ".curator"
    team_dir = curator_dir / "team"
    memory_dir = curator_dir / "memory"

    return CuratorPaths(
        project_root=root,
        curator_dir=curator_dir,
        database=curator_dir / "curator.sqlite",
        goals_dir=curator_dir / "goals",
        team_dir=team_dir,
        roles_dir=team_dir / "roles",
        memory_dir=memory_dir,
        role_memory_dir=memory_dir / "roles",
        sessions_dir=curator_dir / "sessions",
        worktrees_dir=curator_dir / "worktrees",
        logs_dir=curator_dir / "logs",
    )


def build_agentctl_paths(project_root: Path | str) -> CuratorPaths:
    """Build Curator paths using the legacy AgentCTL function alias."""
    return build_curator_paths(project_root)

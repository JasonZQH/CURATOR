"""Detect project stack signals used by the init proposal."""

from pathlib import Path


def detect_project_type(project_root: Path | str) -> str:
    """Detect a coarse project type from root-level project files."""
    root = Path(project_root)

    if (root / "pyproject.toml").exists():
        return "python"
    if (root / "package.json").exists():
        return "javascript"

    return "unknown"

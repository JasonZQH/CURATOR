"""Define Curator initialization models."""

from pathlib import Path

from pydantic import Field

from curator.core.models.base import CuratorModel
from curator.core.models.paths import CuratorPaths


class InitProposal(CuratorModel):
    """Describe the project-local state that init may create after review."""

    project_root: Path
    paths: CuratorPaths
    detected_project_type: str | None = None
    proposed_files: list[Path] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

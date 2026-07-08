"""Define report models for Curator diagnostics commands."""

from dataclasses import dataclass, field
from pathlib import Path

from agentctl.team.roles import RoleContractLoadWarning


@dataclass(frozen=True)
class DoctorCheck:
    """Describe one doctor check result."""

    status: str
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    """Describe the local project health summary for doctor output."""

    project_root: Path
    package_version: str
    python_version: str
    state_dir: Path
    database: Path
    initialized: bool
    recommended_next_step: str
    mode: str = "setup"
    checks: dict[str, DoctorCheck] = field(default_factory=dict)


@dataclass(frozen=True)
class StatusReport:
    """Describe the current Curator project state for status output."""

    project_root: Path
    state_dir: Path
    database: Path
    initialized: bool
    session_count: int
    next_step: str
    mode: str = "setup"
    last_session_id: str | None = None
    last_decision: str | None = None
    last_stop_condition: str | None = None
    contract_warnings: list[RoleContractLoadWarning] = field(default_factory=list)

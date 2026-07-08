"""Define Curator goal proposal, approval, and ledger models."""

from datetime import datetime
from typing import Any

from pydantic import Field

from agentctl.core.enums import EvidenceKind, GoalStatus, RoleName
from agentctl.core.models.base import CuratorModel


class GoalCriterion(CuratorModel):
    """Describe one goal completion criterion and its verifier."""

    id: str
    description: str
    verifier_role: RoleName


class GoalVerification(CuratorModel):
    """Describe commands and evidence required to verify a goal."""

    commands: list[str] = Field(default_factory=list)
    required_evidence: list[EvidenceKind] = Field(default_factory=list)


class GoalApprovalGate(CuratorModel):
    """Describe one condition that should pause and ask the user."""

    id: str
    description: str


class GoalContract(CuratorModel):
    """Describe a user goal from proposal through accepted execution."""

    id: str
    source_request: str
    summary: str
    status: GoalStatus = GoalStatus.PROPOSED
    accepted_by_user: bool = False
    done_criteria: list[GoalCriterion] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    verification: GoalVerification = Field(default_factory=GoalVerification)
    ask_user_when: list[str] = Field(default_factory=list)
    session_id: str | None = None
    loop_run_id: str | None = None
    created_at: datetime | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalRevisionRecord(CuratorModel):
    """Describe one immutable accepted goal snapshot in SQLite."""

    id: str
    goal_id: str
    revision: int
    status: GoalStatus
    contract: dict[str, Any]
    created_at: datetime
    accepted_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalRunRecord(CuratorModel):
    """Describe one accepted goal revision mapped to a loop run."""

    id: str
    goal_id: str
    goal_revision_id: str
    session_id: str
    loop_run_id: str
    status: GoalStatus
    started_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalAcceptance(CuratorModel):
    """Describe the accepted goal and immutable revision id."""

    goal: GoalContract
    revision_id: str

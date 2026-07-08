"""Define Curator role contract and role selection models."""

from datetime import datetime
from typing import Any

from pydantic import Field

from agentctl.core.enums import EvidenceKind
from agentctl.core.models.base import CuratorModel


class RoleCollaborator(CuratorModel):
    """Describe one role another role can intentionally collaborate with."""

    role_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleHandoffRule(CuratorModel):
    """Describe a contract-level role handoff that routing can consume."""

    trigger: str = Field(min_length=1)
    to_role_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    required_evidence: list[EvidenceKind] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleContract(CuratorModel):
    """Describe one machine-readable role contract used by loop compilation."""

    id: str
    display_name: str
    responsibilities: list[str] = Field(default_factory=list)
    when_to_involve: list[str] = Field(default_factory=list)
    expected_evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    collaborators: list[RoleCollaborator] = Field(default_factory=list)
    handoff_rules: list[RoleHandoffRule] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleSelection(CuratorModel):
    """Describe why a role contract was selected as a workflow candidate."""

    role_id: str
    display_name: str
    matched_signals: list[str] = Field(default_factory=list)
    score: int
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleSelectionRecord(RoleSelection):
    """Describe one durable role selection decision for workflow audit."""

    id: str
    session_id: str
    loop_run_id: str
    created_at: datetime

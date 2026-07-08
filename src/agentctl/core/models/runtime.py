"""Define durable runtime readiness records."""

from datetime import datetime
from typing import Any

from pydantic import Field

from agentctl.core.enums import (
    ApprovalKind,
    ApprovalStatus,
    AssignmentStatus,
    DiscoveryStatus,
    PauseStatus,
    ProviderBindingStatus,
    ProviderErrorKind,
    ProviderName,
    ProviderProfileStatus,
    ProviderRunStatus,
    ProviderSessionStatus,
    QuotaStatus,
    RoleInstanceStatus,
    RoleName,
    WorkItemKind,
    WorkItemStatus,
)
from agentctl.core.models.base import CuratorModel


class DiscoverySessionRecord(CuratorModel):
    """Describe one pre-goal PM discovery discussion."""

    id: str
    project_root: str
    status: DiscoveryStatus
    created_at: datetime
    updated_at: datetime
    goal_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscussionTurnRecord(CuratorModel):
    """Describe one durable discovery conversation turn."""

    id: str
    discovery_session_id: str
    role: str
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalDraftRecord(CuratorModel):
    """Describe one durable pre-acceptance goal draft."""

    id: str
    discovery_session_id: str
    goal_id: str
    status: DiscoveryStatus
    contract: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class PauseRecord(CuratorModel):
    """Describe one durable loop pause cursor."""

    id: str
    loop_run_id: str
    session_id: str
    iteration_id: str
    task_id: str | None
    reason: str
    question: str
    requested_input: str
    resume_mode: str
    status: PauseStatus
    created_at: datetime
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeEventRecord(CuratorModel):
    """Describe one user resume answer for a pause."""

    id: str
    pause_id: str
    loop_run_id: str
    session_id: str
    message: str
    action: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderRunRecord(CuratorModel):
    """Describe one provider execution ledger entry."""

    id: str
    provider: ProviderName
    provider_profile_id: str | None = None
    provider_session_id: str | None = None
    session_id: str
    loop_run_id: str
    iteration_id: str
    role: RoleName
    status: ProviderRunStatus
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    error_kind: ProviderErrorKind | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderProfileRecord(CuratorModel):
    """Describe one configured provider identity profile."""

    id: str
    provider: ProviderName
    label: str
    credential_ref: str
    status: ProviderProfileStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleProviderBindingRecord(CuratorModel):
    """Describe one role instance binding to a provider profile."""

    id: str
    role_instance_id: str
    provider_profile_id: str
    status: ProviderBindingStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderSessionRecord(CuratorModel):
    """Describe one runtime session for a provider profile."""

    id: str
    provider_profile_id: str
    status: ProviderSessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuotaStateRecord(CuratorModel):
    """Describe one observed quota state for a provider profile."""

    id: str
    provider_profile_id: str
    status: QuotaStatus
    reason: str
    observed_at: datetime
    reset_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextPackageRecord(CuratorModel):
    """Describe one persisted context package reference."""

    id: str
    session_id: str
    loop_run_id: str
    role: RoleName
    task_id: str | None
    package: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    iteration_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntryRecord(CuratorModel):
    """Describe one SQLite-backed memory summary."""

    id: str
    scope: str
    role: RoleName | None
    source_ref: str
    summary: str
    kind: str = "note"
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleInstanceRecord(CuratorModel):
    """Describe one durable PM, Engineer, or QA pool worker."""

    id: str
    role: RoleName
    label: str
    status: RoleInstanceStatus
    capabilities: list[str] = Field(default_factory=list)
    current_session_id: str | None = None
    current_goal_id: str | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkItemRecord(CuratorModel):
    """Describe one durable queue item owned by the runtime scheduler."""

    id: str
    session_id: str
    goal_id: str | None = None
    goal_revision_id: str | None = None
    kind: WorkItemKind
    required_role: RoleName
    title: str
    description: str
    status: WorkItemStatus
    priority: int = 100
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssignmentRecord(CuratorModel):
    """Describe one durable mapping from queued work to a role instance."""

    id: str
    work_item_id: str
    role_instance_id: str
    session_id: str
    goal_id: str | None = None
    status: AssignmentStatus
    assigned_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequestRecord(CuratorModel):
    """Describe one scoped user approval request."""

    id: str
    session_id: str
    kind: ApprovalKind
    title: str
    description: str
    status: ApprovalStatus
    requested_by: str
    scope: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRecord(CuratorModel):
    """Describe one user decision for an approval request."""

    id: str
    approval_request_id: str
    decision: ApprovalStatus
    decided_by: str
    message: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

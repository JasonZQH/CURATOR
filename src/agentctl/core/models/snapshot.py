"""Define Curator workflow read model snapshots."""

from pydantic import Field

from agentctl.core.models.base import CuratorModel
from agentctl.core.models.loops import (
    EvidenceRef,
    LoopDecisionRecord,
    LoopIterationRecord,
    LoopRunRecord,
)
from agentctl.core.models.roles import RoleSelectionRecord
from agentctl.core.models.runtime import (
    ContextPackageRecord,
    PauseRecord,
    ProviderRunRecord,
    ResumeEventRecord,
)
from agentctl.core.models.session import EventRecord, MessageRecord, SessionRecord, TaskRecord


class WorkflowSnapshot(CuratorModel):
    """Describe the read model consumed by TUI and future APIs."""

    session: SessionRecord
    tasks: list[TaskRecord] = Field(default_factory=list)
    messages: list[MessageRecord] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    loop_runs: list[LoopRunRecord] = Field(default_factory=list)
    loop_iterations: list[LoopIterationRecord] = Field(default_factory=list)
    loop_decisions: list[LoopDecisionRecord] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    role_selections: list[RoleSelectionRecord] = Field(default_factory=list)
    pause_records: list[PauseRecord] = Field(default_factory=list)
    resume_events: list[ResumeEventRecord] = Field(default_factory=list)
    provider_runs: list[ProviderRunRecord] = Field(default_factory=list)
    context_packages: list[ContextPackageRecord] = Field(default_factory=list)

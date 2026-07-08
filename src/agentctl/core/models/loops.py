"""Define Curator loop template, plan, ledger, and evidence models."""

from datetime import datetime
from typing import Any

from pydantic import Field

from agentctl.core.enums import (
    EvidenceKind,
    HarnessStatus,
    LoopDecisionType,
    LoopStatus,
    LoopStepType,
    RoleName,
    StepExecutorType,
    StopCondition,
)
from agentctl.core.models.base import CuratorModel


class DoneCriteria(CuratorModel):
    """Describe one completion requirement owned by a loop contract."""

    id: str
    description: str


class GuideRef(CuratorModel):
    """Describe a guidance document used to build harness context."""

    id: str
    title: str
    uri: str


class SensorRef(CuratorModel):
    """Describe evidence a loop step must sense before a decision."""

    id: str
    description: str
    required_evidence_kind: EvidenceKind


class LoopTemplate(CuratorModel):
    """Describe a Curator-owned loop blueprint before session binding."""

    id: str
    name: str
    steps: list[LoopStepType]
    done_criteria: list[DoneCriteria] = Field(default_factory=list)
    guide_refs: list[GuideRef] = Field(default_factory=list)
    sensor_refs: list[SensorRef] = Field(default_factory=list)
    allowed_decisions: list[LoopDecisionType] = Field(default_factory=list)
    stop_conditions: list[StopCondition] = Field(default_factory=list)


class LoopContract(CuratorModel):
    """Describe the session-bound loop constraints derived from a template."""

    id: str
    session_id: str
    template_id: str
    steps: list[LoopStepType]
    done_criteria: list[DoneCriteria] = Field(default_factory=list)
    guide_refs: list[GuideRef] = Field(default_factory=list)
    sensor_refs: list[SensorRef] = Field(default_factory=list)
    allowed_decisions: list[LoopDecisionType] = Field(default_factory=list)
    stop_conditions: list[StopCondition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompiledLoopStep(CuratorModel):
    """Describe one scheduler-ready step compiled from role and loop contracts."""

    id: str
    role_id: str
    task_id: str
    task_title: str
    sequence: int
    step_type: LoopStepType
    role: RoleName
    executor: StepExecutorType = StepExecutorType.PROVIDER
    slot: str | None = None
    max_retries: int = 1
    required_evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    decision_on_success: LoopDecisionType
    stop_condition_on_success: StopCondition | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompiledLoopPlan(CuratorModel):
    """Describe the executable loop plan produced by the system compiler."""

    id: str
    session_id: str
    contract_id: str
    template_id: str
    steps: list[CompiledLoopStep]
    guide_refs: list[GuideRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LoopRunRecord(CuratorModel):
    """Describe one durable execution instance of a loop contract."""

    id: str
    session_id: str
    contract_id: str
    template_id: str
    status: LoopStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LoopIterationRecord(CuratorModel):
    """Describe one ordered execution attempt inside a loop run."""

    id: str
    loop_run_id: str
    session_id: str
    sequence: int
    step_type: LoopStepType
    role: RoleName
    status: HarnessStatus
    started_at: datetime
    task_id: str | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LoopDecisionRecord(CuratorModel):
    """Describe one scheduler-owned decision after a loop iteration."""

    id: str
    loop_run_id: str
    iteration_id: str
    decision: LoopDecisionType
    reason: str
    created_at: datetime
    stop_condition: StopCondition | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(CuratorModel):
    """Describe one durable reference to evidence produced by a loop iteration."""

    id: str
    session_id: str
    loop_run_id: str
    iteration_id: str
    kind: EvidenceKind
    uri: str
    summary: str
    producer_role: RoleName
    created_at: datetime
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

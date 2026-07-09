"""Define Curator harness and provider output models."""

from typing import Any

from pydantic import Field

from curator.core.enums import HarnessStatus, LoopStepType, ProviderName, RoleName, TaskStatus
from curator.core.models.base import CuratorModel
from curator.core.models.loops import EvidenceRef, GuideRef
from curator.core.models.session import EventRecord, MessageRecord


class HarnessRunSpec(CuratorModel):
    """Describe the input contract passed from scheduler to harness."""

    id: str
    session_id: str
    loop_run_id: str
    iteration_id: str
    role: RoleName
    step_type: LoopStepType
    task_id: str
    context_refs: list[EvidenceRef] = Field(default_factory=list)
    guide_refs: list[GuideRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HarnessRunResult(CuratorModel):
    """Describe the structured result returned from a harness execution."""

    spec_id: str
    status: HarnessStatus
    role: RoleName
    step_type: LoopStepType
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PMPlanOutput(CuratorModel):
    """Describe the PM provider output for the planning step."""

    summary: str
    tasks: list[str] = Field(default_factory=list)
    done_criteria: list[str] = Field(default_factory=list)


class EngineerImplementationOutput(CuratorModel):
    """Describe the Engineer provider output for the implementation step."""

    summary: str
    changed_files: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)


class QAValidationOutput(CuratorModel):
    """Describe the QA provider output for the validation step."""

    passed: bool
    summary: str
    checks: list[str] = Field(default_factory=list)


class PMConfirmationOutput(CuratorModel):
    """Describe the PM provider output for confirmation after QA validation."""

    confirmed: bool
    summary: str
    aligned_done_criteria: list[str] = Field(default_factory=list)


class ProviderRunResult(CuratorModel):
    """Describe the structured result returned by a provider run."""

    provider: ProviderName
    role: RoleName
    task_id: str
    status: TaskStatus
    output: str
    messages: list[MessageRecord] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

"""Define provider readiness request, response, and error contracts."""

from typing import Any

from pydantic import Field

from curator.context.packaging import ContextPackage
from curator.core.enums import (
    LoopStepType,
    ProviderErrorKind,
    ProviderName,
    ProviderRunStatus,
    RoleName,
)
from curator.core.models.base import CuratorModel
from curator.core.schema import EvidenceRef, HarnessRunSpec


class HandoffRequest(CuratorModel):
    """Describe a provider-requested human handoff signal."""

    reason: str
    question: str
    requested_input: str = "natural language guidance"


class ScopeChangeSignal(CuratorModel):
    """Describe a provider-observed possible scope change."""

    summary: str
    recommendation: str = "create_goal_revision"


class ProviderCancelledError(Exception):
    """Signal that a provider run was cancelled by user or runtime."""


class ProviderRunRequest(CuratorModel):
    """Describe the typed input contract for one provider run."""

    id: str
    session_id: str
    loop_run_id: str
    iteration_id: str
    role: RoleName
    step_type: LoopStepType
    task_id: str
    goal_snapshot: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    disallowed_actions: list[str] = Field(default_factory=list)
    context_package_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_harness_spec(cls, spec: HarnessRunSpec) -> "ProviderRunRequest":
        """Build a provider request from the legacy harness spec."""
        return cls(
            id=spec.id,
            session_id=spec.session_id,
            loop_run_id=spec.loop_run_id,
            iteration_id=spec.iteration_id,
            role=spec.role,
            step_type=spec.step_type,
            task_id=spec.task_id,
            evidence_refs=spec.context_refs,
            allowed_actions=["read_file", "write_file"],
            disallowed_actions=["destructive_shell", "remote_vcs_write"],
            metadata=spec.metadata,
        )

    @classmethod
    def from_context_package(
        cls, spec: HarnessRunSpec, package: ContextPackage
    ) -> "ProviderRunRequest":
        """Build a provider request from the persisted context package."""
        return cls(
            id=spec.id,
            session_id=spec.session_id,
            loop_run_id=spec.loop_run_id,
            iteration_id=spec.iteration_id,
            role=spec.role,
            step_type=spec.step_type,
            task_id=spec.task_id,
            goal_snapshot=package.goal_snapshot,
            evidence_refs=spec.context_refs,
            constraints=package.constraints,
            allowed_actions=package.allowed_actions,
            disallowed_actions=package.disallowed_actions,
            context_package_id=package.id,
            metadata={
                **spec.metadata,
                "context_package_id": package.id,
                "memory_summaries": package.memory_summaries,
                "repo_state_summary": package.repo_state_summary,
            },
        )


class ProviderRunResponse(CuratorModel):
    """Describe the typed output contract for one provider run."""

    provider: ProviderName
    request_id: str
    status: ProviderRunStatus
    output: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    handoff_request: HandoffRequest | None = None
    scope_change: ScopeChangeSignal | None = None
    error_kind: ProviderErrorKind | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def succeeded(
        cls,
        request: ProviderRunRequest,
        provider: ProviderName,
        output: dict[str, Any],
    ) -> "ProviderRunResponse":
        """Build a successful provider response."""
        return cls(
            provider=provider,
            request_id=request.id,
            status=ProviderRunStatus.SUCCEEDED,
            output=output,
        )

    @classmethod
    def failed(
        cls,
        request: ProviderRunRequest,
        provider: ProviderName,
        error_kind: ProviderErrorKind,
        error_message: str,
    ) -> "ProviderRunResponse":
        """Build a failed provider response."""
        return cls(
            provider=provider,
            request_id=request.id,
            status=ProviderRunStatus.FAILED,
            error_kind=error_kind,
            error_message=error_message,
        )


def classify_provider_error(error: Exception) -> ProviderErrorKind:
    """Return the provider error kind represented by an exception."""
    if isinstance(error, ProviderCancelledError):
        return ProviderErrorKind.CANCELLED
    if isinstance(error, TimeoutError):
        return ProviderErrorKind.TIMEOUT
    if isinstance(error, PermissionError):
        return ProviderErrorKind.PERMISSION_DENIED
    if isinstance(error, (TypeError, ValueError)):
        return ProviderErrorKind.INVALID_OUTPUT

    return ProviderErrorKind.PROVIDER_UNAVAILABLE

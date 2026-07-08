"""Evaluate provider action requests before execution."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from agentctl.core.enums import ActionType, ApprovalKind, ApprovalStatus
from agentctl.core.models.base import CuratorModel
from agentctl.core.schema import ApprovalRequestRecord
from agentctl.state.repositories import insert_approval_request


class ActionRequest(CuratorModel):
    """Describe one provider-requested action."""

    type: ActionType
    target: str | None = None
    command: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ActionDecision(CuratorModel):
    """Describe the policy decision for an action request."""

    allowed: bool
    reason: str
    approval_required: bool = False
    handoff_required: bool = False


class ActionPolicy(CuratorModel):
    """Describe project-scoped provider action boundaries."""

    project_root: Path
    readable_roots: list[Path] = Field(default_factory=list)
    writable_roots: list[Path] = Field(default_factory=list)

    @classmethod
    def for_project(cls, project_root: Path | str) -> "ActionPolicy":
        """Build the default local action policy for a project."""
        root = Path(project_root).resolve()
        return cls(project_root=root, readable_roots=[root], writable_roots=[root])

    def evaluate(self, request: ActionRequest) -> ActionDecision:
        """Evaluate one action request against this policy."""
        if request.type is ActionType.READ_FILE:
            return self._evaluate_path_request(request, self.readable_roots, "Read")
        if request.type is ActionType.WRITE_FILE:
            return self._evaluate_path_request(request, self.writable_roots, "Write")
        if request.type is ActionType.SHELL_COMMAND:
            return self._evaluate_shell_request(request)
        if request.type is ActionType.VCS_REMOTE_WRITE:
            return ActionDecision(
                allowed=False,
                approval_required=True,
                handoff_required=True,
                reason="Remote VCS write actions require user approval.",
            )

        return ActionDecision(
            allowed=False,
            handoff_required=True,
            reason=f"Unsupported action type: {request.type.value}",
        )

    def record_gate(
        self,
        connection: sqlite3.Connection,
        request: ActionRequest,
        session_id: str,
        requested_by: str,
        now: datetime | None = None,
    ) -> ApprovalRequestRecord | None:
        """Persist an approval request when an action cannot execute directly."""
        decision = self.evaluate(request)
        if decision.allowed and not decision.approval_required and not decision.handoff_required:
            return None

        timestamp = now or datetime.now(UTC)
        kind = self._approval_kind_for_request(request)
        approval = ApprovalRequestRecord(
            id=self._approval_id_for_request(kind, request),
            session_id=session_id,
            kind=kind,
            title=self._approval_title(kind),
            description=self._approval_description(decision, kind),
            status=ApprovalStatus.PENDING,
            requested_by=requested_by,
            scope=self._approval_scope_for_request(request, decision),
            created_at=timestamp,
            updated_at=timestamp,
        )
        insert_approval_request(connection, approval)
        return approval

    def _approval_kind_for_request(self, request: ActionRequest) -> ApprovalKind:
        """Return the approval category for one gated action."""
        if request.type is ActionType.SHELL_COMMAND:
            return ApprovalKind.DESTRUCTIVE_ACTION
        if request.type is ActionType.VCS_REMOTE_WRITE:
            return ApprovalKind.EXTERNAL_WRITE
        return ApprovalKind.PERMISSION

    def _approval_id_for_request(
        self, kind: ApprovalKind, request: ActionRequest
    ) -> str:
        """Return a deterministic approval id for one gated request."""
        raw = request.command or request.target or request.type.value
        slug = "".join(character if character.isalnum() else "-" for character in raw.lower())
        slug = "-".join(part for part in slug.split("-") if part)
        return f"approval-{kind.value.replace('_', '-')}-{slug[:48]}"

    def _approval_title(self, kind: ApprovalKind) -> str:
        """Return a short title for one approval category."""
        if kind is ApprovalKind.DESTRUCTIVE_ACTION:
            return "Destructive shell command requires approval"
        if kind is ApprovalKind.EXTERNAL_WRITE:
            return "External write requires approval"
        return "Permission requires user guidance"

    def _approval_description(
        self, decision: ActionDecision, kind: ApprovalKind
    ) -> str:
        """Return a user-facing description for one gated action."""
        if kind is ApprovalKind.PERMISSION and decision.handoff_required:
            return "Permission requires user guidance before this action can continue."
        return decision.reason

    def _approval_scope_for_request(
        self, request: ActionRequest, decision: ActionDecision
    ) -> dict[str, str]:
        """Return the scoped action payload stored with an approval request."""
        scope = {
            "action_type": request.type.value,
            "reason": decision.reason,
        }
        if request.target is not None:
            scope["target"] = request.target
        if request.command is not None:
            scope["command"] = request.command
        scope.update(request.metadata)
        return scope

    def _evaluate_path_request(
        self, request: ActionRequest, roots: list[Path], label: str
    ) -> ActionDecision:
        """Evaluate a file path action against allowed roots."""
        if request.target is None:
            return ActionDecision(
                allowed=False,
                handoff_required=True,
                reason=f"{label} action requires a target path.",
            )

        target = Path(request.target).expanduser().resolve()
        if any(target == root or root in target.parents for root in roots):
            return ActionDecision(allowed=True, reason=f"{label} is within project policy.")

        return ActionDecision(
            allowed=False,
            handoff_required=True,
            reason=f"{label} target is outside allowed project roots.",
        )

    def _evaluate_shell_request(self, request: ActionRequest) -> ActionDecision:
        """Evaluate a shell command request for destructive patterns."""
        command = request.command or ""
        destructive_tokens = ["rm -rf", "git reset", "git checkout --", "chmod -R"]
        if any(token in command for token in destructive_tokens):
            return ActionDecision(
                allowed=False,
                approval_required=True,
                handoff_required=True,
                reason="Destructive shell commands require user approval.",
            )

        return ActionDecision(allowed=True, reason="Shell command is allowed by policy.")

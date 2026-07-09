"""Define VCS readiness abstractions without remote API calls."""

from pathlib import Path
from typing import Any

from pydantic import Field

from curator.core.enums import ActionType
from curator.core.models.base import CuratorModel
from curator.runtime.action_policy import ActionRequest


class DiffRef(CuratorModel):
    """Describe one durable reference to a local diff or changed path."""

    id: str
    path: str
    summary: str
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepoStateSummary(CuratorModel):
    """Describe the local repository state passed across runtime boundaries."""

    project_root: str
    is_git_repo: bool
    branch: str | None = None
    diff_refs: list[DiffRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BranchIntent(CuratorModel):
    """Describe a future branch operation without performing it."""

    name: str
    base: str
    purpose: str


class PullRequestIntent(CuratorModel):
    """Describe a future pull request operation without performing it."""

    title: str
    body: str
    base: str
    head: str


class RemoteActionRequest(CuratorModel):
    """Describe a future remote VCS write request."""

    id: str
    provider: str
    action: str
    branch: BranchIntent | None = None
    pull_request: PullRequestIntent | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_action_request(self) -> ActionRequest:
        """Convert the remote request into an action policy request."""
        metadata = {
            "remote_request_id": self.id,
            "provider": self.provider,
            "remote_action": self.action,
            **self.metadata,
        }
        if self.branch is not None:
            metadata.update(
                {
                    "branch_name": self.branch.name,
                    "branch_base": self.branch.base,
                    "branch_purpose": self.branch.purpose,
                }
            )
        if self.pull_request is not None:
            metadata.update(
                {
                    "pr_title": self.pull_request.title,
                    "pr_base": self.pull_request.base,
                    "pr_head": self.pull_request.head,
                }
            )
        return ActionRequest(
            type=ActionType.VCS_REMOTE_WRITE,
            target=f"{self.provider}://{self.action}",
            metadata=metadata,
        )


def build_repo_state_summary(
    project_root: Path | str,
    diff_refs: list[DiffRef] | None = None,
) -> RepoStateSummary:
    """Build a local repository summary without calling remote APIs."""
    root = Path(project_root)
    return RepoStateSummary(
        project_root=str(root),
        is_git_repo=(root / ".git").exists(),
        diff_refs=diff_refs or [],
        metadata={"remote_api_called": False},
    )

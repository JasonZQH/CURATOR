"""Verify VCS and GitHub readiness boundaries without calling remote APIs."""

from datetime import UTC, datetime

from curator.core.enums import ApprovalKind, ApprovalStatus
from curator.core.paths import build_curator_paths
from curator.runtime.action_policy import ActionPolicy
from curator.runtime.vcs import (
    BranchIntent,
    DiffRef,
    PullRequestIntent,
    RemoteActionRequest,
    build_repo_state_summary,
)
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import load_approval_requests


def _connection(tmp_path):
    """Open an initialized Curator database for a temporary project."""
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    return connection


def test_repo_state_summary_captures_diff_refs_without_git_api(tmp_path):
    """Verify local repo summaries can carry diff refs without GitHub access."""
    diff = DiffRef(
        id="diff-login-css",
        path="src/login.css",
        summary="Login layout spacing changed.",
    )

    summary = build_repo_state_summary(tmp_path, diff_refs=[diff])

    assert summary.project_root == str(tmp_path)
    assert summary.is_git_repo is False
    assert summary.diff_refs == [diff]
    assert summary.metadata["remote_api_called"] is False


def test_remote_pr_intent_becomes_scoped_approval_request(tmp_path):
    """Verify GitHub-like writes use action policy approval instead of remote calls."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    branch = BranchIntent(name="curator/login-layout", base="main", purpose="Fix login layout")
    pull_request = PullRequestIntent(
        title="Fix login layout",
        body="Implements the accepted Curator goal.",
        base="main",
        head=branch.name,
    )
    request = RemoteActionRequest(
        id="remote-pr-1",
        provider="github",
        action="open_pull_request",
        branch=branch,
        pull_request=pull_request,
    )
    connection = _connection(tmp_path)
    try:
        approval = ActionPolicy.for_project(tmp_path).record_gate(
            connection,
            request=request.to_action_request(),
            session_id="session-router",
            requested_by="pm.coordinator",
            now=now,
        )
        approvals = load_approval_requests(connection)
    finally:
        connection.close()

    assert approval is not None
    assert approval.kind is ApprovalKind.EXTERNAL_WRITE
    assert approval.status is ApprovalStatus.PENDING
    assert approvals[0].scope["provider"] == "github"
    assert approvals[0].scope["remote_action"] == "open_pull_request"
    assert approvals[0].scope["pr_title"] == "Fix login layout"

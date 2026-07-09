"""Build role-specific context packages from durable state."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from curator.core.enums import RoleName
from curator.core.models.base import CuratorModel
from curator.core.schema import ContextPackageRecord, GoalContract
from curator.runtime.action_policy import ActionPolicy
from curator.state.repositories import (
    insert_context_package,
    load_evidence_refs_for_run,
    load_goal_revision,
    load_latest_goal_run,
    load_memory_entries,
)

MAX_MEMORY_ENTRIES = 5
MAX_MEMORY_ENTRY_CHARS = 400
MAX_MEMORY_TOTAL_CHARS = 1200


class ContextPackage(CuratorModel):
    """Describe a role-specific provider context package."""

    id: str
    session_id: str
    loop_run_id: str
    role: RoleName
    task_id: str | None
    project_root: str
    goal_snapshot: dict[str, Any] = Field(default_factory=dict)
    evidence_summaries: dict[str, str] = Field(default_factory=dict)
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    memory_summaries: list[str] = Field(default_factory=list)
    repo_state_summary: str
    constraints: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    disallowed_actions: list[str] = Field(default_factory=list)
    iteration_id: str | None = None


class PMResearchPacket(CuratorModel):
    """Describe PM-readable research context backed by evidence refs."""

    project_root: str
    goal_snapshot: dict[str, Any] = Field(default_factory=dict)
    evidence_summaries: dict[str, str] = Field(default_factory=dict)
    open_risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    evidence_ref_ids: list[str] = Field(default_factory=list)


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def _goal_snapshot(
    connection: sqlite3.Connection,
    goal_contract: GoalContract | None = None,
) -> dict[str, Any]:
    """Return the accepted goal snapshot for this run.

    An explicit goal contract always wins; the latest-goal-run fallback exists
    only for callers that predate goal threading and is not session-scoped.
    """
    if goal_contract is not None:
        return goal_contract.model_dump(mode="json")

    goal_run = load_latest_goal_run(connection)
    if goal_run is None:
        return {}

    revision = load_goal_revision(connection, goal_run.goal_revision_id)
    if revision is None:
        return {}

    return revision.contract


def _repo_summary(project_root: Path | str) -> str:
    """Return a concise local repository state summary."""
    root = Path(project_root)
    return f"Project root: {root}"


def _evidence_summary_map(connection: sqlite3.Connection, loop_run_id: str) -> dict[str, str]:
    """Return evidence summaries keyed by evidence kind."""
    evidence_refs = load_evidence_refs_for_run(connection, loop_run_id)
    return {evidence.kind.value: evidence.summary for evidence in evidence_refs}


def _memory_summaries(
    connection: sqlite3.Connection,
    scope: str,
    role: RoleName,
) -> list[str]:
    """Return bounded memory lessons for one role at one project scope."""
    entries = load_memory_entries(connection, scope, role=role, limit=MAX_MEMORY_ENTRIES)
    summaries: list[str] = []
    total = 0
    for entry in entries:
        summary = entry.summary[:MAX_MEMORY_ENTRY_CHARS]
        if total + len(summary) > MAX_MEMORY_TOTAL_CHARS:
            break
        summaries.append(summary)
        total += len(summary)
    return summaries


def _evidence_items(connection: sqlite3.Connection, loop_run_id: str) -> list[dict[str, Any]]:
    """Return every evidence ref for this run without collapsing repeated kinds."""
    evidence_refs = load_evidence_refs_for_run(connection, loop_run_id)
    return [
        {
            "id": evidence.id,
            "kind": evidence.kind.value,
            "summary": evidence.summary,
            "producer_role": evidence.producer_role.value,
            "iteration_id": evidence.iteration_id,
        }
        for evidence in evidence_refs
    ]


def build_context_package(
    connection: sqlite3.Connection,
    session_id: str,
    loop_run_id: str,
    iteration_id: str | None,
    role: RoleName,
    task_id: str | None,
    project_root: Path | str,
    goal_contract: GoalContract | None = None,
) -> ContextPackage:
    """Build and persist one role-specific context package."""
    policy = ActionPolicy.for_project(project_root)
    package_id = f"context-{loop_run_id}-{iteration_id or 'pending'}-{role.value}"
    package = ContextPackage(
        id=package_id,
        session_id=session_id,
        loop_run_id=loop_run_id,
        iteration_id=iteration_id,
        role=role,
        task_id=task_id,
        project_root=str(project_root),
        goal_snapshot=_goal_snapshot(connection, goal_contract),
        evidence_summaries=_evidence_summary_map(connection, loop_run_id),
        evidence_items=_evidence_items(connection, loop_run_id),
        memory_summaries=_memory_summaries(connection, str(project_root), role),
        repo_state_summary=_repo_summary(project_root),
        constraints=["Do not expand scope without user approval."],
        allowed_actions=["read_file", "write_file"],
        disallowed_actions=["destructive_shell", "remote_vcs_write"],
    )
    insert_context_package(
        connection,
        ContextPackageRecord(
            id=package.id,
            session_id=session_id,
            loop_run_id=loop_run_id,
            iteration_id=iteration_id,
            role=role,
            task_id=task_id,
            package={
                **package.model_dump(mode="json"),
                "action_policy": policy.model_dump(mode="json"),
            },
            created_at=_now(),
        ),
    )
    return package


def build_pm_research_packet(
    connection: sqlite3.Connection, project_root: Path | str
) -> PMResearchPacket:
    """Build a PM research packet from durable evidence."""
    goal_run = load_latest_goal_run(connection)
    evidence_summaries: dict[str, str] = {}
    evidence_ref_ids: list[str] = []
    if goal_run is not None:
        evidence_refs = load_evidence_refs_for_run(connection, goal_run.loop_run_id)
        evidence_summaries = {
            evidence.kind.value: evidence.summary for evidence in evidence_refs
        }
        evidence_ref_ids = [evidence.id for evidence in evidence_refs]

    unknowns = []
    if "implementation" not in evidence_summaries:
        unknowns.append("implementation evidence is not available")
    if "validation" not in evidence_summaries:
        unknowns.append("validation evidence is not available")

    return PMResearchPacket(
        project_root=str(project_root),
        goal_snapshot=_goal_snapshot(connection),
        evidence_summaries=evidence_summaries,
        unknowns=unknowns,
        evidence_ref_ids=evidence_ref_ids,
    )

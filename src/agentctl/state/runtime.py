"""Persist and load runtime readiness ledger records."""

import sqlite3
from typing import Any

from agentctl.core.enums import RoleName
from agentctl.core.schema import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    AssignmentRecord,
    ContextPackageRecord,
    DiscoverySessionRecord,
    DiscussionTurnRecord,
    GoalDraftRecord,
    MemoryEntryRecord,
    PauseRecord,
    ProviderProfileRecord,
    ProviderRunRecord,
    ProviderSessionRecord,
    QuotaStateRecord,
    ResumeEventRecord,
    RoleInstanceRecord,
    RoleProviderBindingRecord,
    WorkItemRecord,
)
from agentctl.state._mapping import fetch_many, fetch_one, iso_or_none, json_dumps, json_loads


def insert_discovery_session(
    connection: sqlite3.Connection, session: DiscoverySessionRecord
) -> None:
    """Insert or replace one discovery session."""
    connection.execute(
        """
        insert or replace into discovery_sessions (
            id, project_root, status, goal_id, created_at, updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.id,
            session.project_root,
            session.status.value,
            session.goal_id,
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
            json_dumps(session.metadata),
        ),
    )
    connection.commit()


def insert_discussion_turn(
    connection: sqlite3.Connection, turn: DiscussionTurnRecord
) -> None:
    """Insert or replace one discussion turn."""
    connection.execute(
        """
        insert or replace into discussion_turns (
            id, discovery_session_id, role, content, created_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            turn.id,
            turn.discovery_session_id,
            turn.role,
            turn.content,
            turn.created_at.isoformat(),
            json_dumps(turn.metadata),
        ),
    )
    connection.commit()


def insert_goal_draft(connection: sqlite3.Connection, draft: GoalDraftRecord) -> None:
    """Insert or replace one durable goal draft."""
    connection.execute(
        """
        insert or replace into goal_drafts (
            id, discovery_session_id, goal_id, status, contract_json, created_at,
            updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft.id,
            draft.discovery_session_id,
            draft.goal_id,
            draft.status.value,
            json_dumps(draft.contract),
            draft.created_at.isoformat(),
            draft.updated_at.isoformat(),
            json_dumps(draft.metadata),
        ),
    )
    connection.commit()


def insert_pause_record(connection: sqlite3.Connection, pause: PauseRecord) -> None:
    """Insert or replace one durable pause cursor."""
    connection.execute(
        """
        insert or replace into pause_records (
            id, loop_run_id, session_id, iteration_id, task_id, reason, question,
            requested_input, resume_mode, status, created_at, resolved_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pause.id,
            pause.loop_run_id,
            pause.session_id,
            pause.iteration_id,
            pause.task_id,
            pause.reason,
            pause.question,
            pause.requested_input,
            pause.resume_mode,
            pause.status.value,
            pause.created_at.isoformat(),
            iso_or_none(pause.resolved_at),
            json_dumps(pause.metadata),
        ),
    )
    connection.commit()


def insert_resume_event(connection: sqlite3.Connection, event: ResumeEventRecord) -> None:
    """Insert or replace one resume event."""
    connection.execute(
        """
        insert or replace into resume_events (
            id, pause_id, loop_run_id, session_id, message, action, created_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.pause_id,
            event.loop_run_id,
            event.session_id,
            event.message,
            event.action,
            event.created_at.isoformat(),
            json_dumps(event.metadata),
        ),
    )
    connection.commit()


def insert_provider_profile(
    connection: sqlite3.Connection, profile: ProviderProfileRecord
) -> None:
    """Insert or replace one configured provider profile."""
    connection.execute(
        """
        insert or replace into provider_profiles (
            id, provider, label, credential_ref, status, created_at, updated_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile.id,
            profile.provider.value,
            profile.label,
            profile.credential_ref,
            profile.status.value,
            profile.created_at.isoformat(),
            profile.updated_at.isoformat(),
            json_dumps(profile.metadata),
        ),
    )
    connection.commit()


def insert_provider_run(connection: sqlite3.Connection, run: ProviderRunRecord) -> None:
    """Insert or replace one provider run ledger entry."""
    connection.execute(
        """
        insert or replace into provider_runs (
            id, provider, provider_profile_id, provider_session_id, session_id,
            loop_run_id, iteration_id, role, status, request_json, response_json,
            error_kind, error_message, created_at, completed_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.id,
            run.provider.value,
            run.provider_profile_id,
            run.provider_session_id,
            run.session_id,
            run.loop_run_id,
            run.iteration_id,
            run.role.value,
            run.status.value,
            json_dumps(run.request),
            json_dumps(run.response),
            run.error_kind.value if run.error_kind else None,
            run.error_message,
            run.created_at.isoformat(),
            iso_or_none(run.completed_at),
            json_dumps(run.metadata),
        ),
    )
    connection.commit()


def insert_provider_session(
    connection: sqlite3.Connection, session: ProviderSessionRecord
) -> None:
    """Insert or replace one provider profile runtime session."""
    connection.execute(
        """
        insert or replace into provider_sessions (
            id, provider_profile_id, status, started_at, ended_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (
            session.id,
            session.provider_profile_id,
            session.status.value,
            session.started_at.isoformat(),
            iso_or_none(session.ended_at),
            json_dumps(session.metadata),
        ),
    )
    connection.commit()


def insert_quota_state(connection: sqlite3.Connection, quota: QuotaStateRecord) -> None:
    """Insert or replace one observed provider quota state."""
    connection.execute(
        """
        insert or replace into quota_state (
            id, provider_profile_id, status, reason, observed_at, reset_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quota.id,
            quota.provider_profile_id,
            quota.status.value,
            quota.reason,
            quota.observed_at.isoformat(),
            iso_or_none(quota.reset_at),
            json_dumps(quota.metadata),
        ),
    )
    connection.commit()


def insert_context_package(
    connection: sqlite3.Connection, package: ContextPackageRecord
) -> None:
    """Insert or replace one context package record."""
    connection.execute(
        """
        insert or replace into context_packages (
            id, session_id, loop_run_id, iteration_id, role, task_id, package_json,
            created_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            package.id,
            package.session_id,
            package.loop_run_id,
            package.iteration_id,
            package.role.value,
            package.task_id,
            json_dumps(package.package),
            package.created_at.isoformat(),
            json_dumps(package.metadata),
        ),
    )
    connection.commit()


def insert_memory_entry(connection: sqlite3.Connection, entry: MemoryEntryRecord) -> None:
    """Insert or replace one SQLite-backed memory summary."""
    connection.execute(
        """
        insert or replace into memory_entries (
            id, scope, role, source_ref, summary, kind, created_at, updated_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.id,
            entry.scope,
            entry.role.value if entry.role else None,
            entry.source_ref,
            entry.summary,
            entry.kind,
            entry.created_at.isoformat(),
            iso_or_none(entry.updated_at),
            json_dumps(entry.metadata),
        ),
    )
    connection.commit()


def _map_memory_entry(row: sqlite3.Row) -> dict[str, Any]:
    """Map a memory_entries row into MemoryEntryRecord kwargs."""
    return {
        "id": row["id"],
        "scope": row["scope"],
        "role": row["role"],
        "source_ref": row["source_ref"],
        "summary": row["summary"],
        "kind": row["kind"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_memory_entries(
    connection: sqlite3.Connection,
    scope: str,
    role: RoleName | None = None,
    limit: int = 10,
) -> list[MemoryEntryRecord]:
    """Load recent memory entries for one scope, optionally filtered by role."""
    if role is None:
        query = """
            select * from memory_entries
            where scope = ?
            order by created_at desc, id desc
            limit ?
        """
        parameters: tuple[Any, ...] = (scope, limit)
    else:
        query = """
            select * from memory_entries
            where scope = ? and (role = ? or role is null)
            order by created_at desc, id desc
            limit ?
        """
        parameters = (scope, role.value, limit)

    return fetch_many(connection, query, parameters, MemoryEntryRecord, _map_memory_entry)


def insert_role_instance(connection: sqlite3.Connection, role: RoleInstanceRecord) -> None:
    """Insert or replace one durable role instance."""
    connection.execute(
        """
        insert or replace into role_instances (
            id, role, label, status, capabilities_json, current_session_id,
            current_goal_id, last_used_at, created_at, updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            role.id,
            role.role.value,
            role.label,
            role.status.value,
            json_dumps(role.capabilities),
            role.current_session_id,
            role.current_goal_id,
            iso_or_none(role.last_used_at),
            role.created_at.isoformat(),
            role.updated_at.isoformat(),
            json_dumps(role.metadata),
        ),
    )
    connection.commit()


def insert_role_provider_binding(
    connection: sqlite3.Connection, binding: RoleProviderBindingRecord
) -> None:
    """Insert or replace one role instance provider profile binding."""
    if binding.status.value == "active":
        connection.execute(
            """
            update role_provider_bindings
            set status = 'inactive', updated_at = ?
            where role_instance_id = ? and status = 'active' and id != ?
            """,
            (binding.updated_at.isoformat(), binding.role_instance_id, binding.id),
        )
    connection.execute(
        """
        insert or replace into role_provider_bindings (
            id, role_instance_id, provider_profile_id, status, created_at,
            updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            binding.id,
            binding.role_instance_id,
            binding.provider_profile_id,
            binding.status.value,
            binding.created_at.isoformat(),
            binding.updated_at.isoformat(),
            json_dumps(binding.metadata),
        ),
    )
    connection.commit()


def insert_work_item(connection: sqlite3.Connection, item: WorkItemRecord) -> None:
    """Insert or replace one durable work item."""
    connection.execute(
        """
        insert or replace into work_items (
            id, session_id, goal_id, goal_revision_id, kind, required_role, title,
            description, status, priority, created_at, updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            item.session_id,
            item.goal_id,
            item.goal_revision_id,
            item.kind.value,
            item.required_role.value,
            item.title,
            item.description,
            item.status.value,
            item.priority,
            item.created_at.isoformat(),
            item.updated_at.isoformat(),
            json_dumps(item.metadata),
        ),
    )
    connection.commit()


def insert_assignment(connection: sqlite3.Connection, assignment: AssignmentRecord) -> None:
    """Insert or replace one durable worker assignment."""
    connection.execute(
        """
        insert or replace into assignments (
            id, work_item_id, role_instance_id, session_id, goal_id, status,
            assigned_at, completed_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assignment.id,
            assignment.work_item_id,
            assignment.role_instance_id,
            assignment.session_id,
            assignment.goal_id,
            assignment.status.value,
            assignment.assigned_at.isoformat(),
            iso_or_none(assignment.completed_at),
            json_dumps(assignment.metadata),
        ),
    )
    connection.commit()


def insert_approval_request(
    connection: sqlite3.Connection, approval: ApprovalRequestRecord
) -> None:
    """Insert or replace one scoped approval request."""
    connection.execute(
        """
        insert or replace into approval_requests (
            id, session_id, kind, title, description, status, requested_by, scope_json,
            created_at, updated_at, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval.id,
            approval.session_id,
            approval.kind.value,
            approval.title,
            approval.description,
            approval.status.value,
            approval.requested_by,
            json_dumps(approval.scope),
            approval.created_at.isoformat(),
            approval.updated_at.isoformat(),
            json_dumps(approval.metadata),
        ),
    )
    connection.commit()


def insert_approval_decision(
    connection: sqlite3.Connection, decision: ApprovalDecisionRecord
) -> None:
    """Insert or replace one approval decision."""
    connection.execute(
        """
        insert or replace into approval_decisions (
            id, approval_request_id, decision, decided_by, message, created_at,
            metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.id,
            decision.approval_request_id,
            decision.decision.value,
            decision.decided_by,
            decision.message,
            decision.created_at.isoformat(),
            json_dumps(decision.metadata),
        ),
    )
    connection.commit()


def _map_discovery_session(row: sqlite3.Row) -> dict[str, Any]:
    """Map a discovery_sessions row into DiscoverySessionRecord kwargs."""
    return {
        "id": row["id"],
        "project_root": row["project_root"],
        "status": row["status"],
        "goal_id": row["goal_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_discussion_turn(row: sqlite3.Row) -> dict[str, Any]:
    """Map a discussion_turns row into DiscussionTurnRecord kwargs."""
    return {
        "id": row["id"],
        "discovery_session_id": row["discovery_session_id"],
        "role": row["role"],
        "content": row["content"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_goal_draft(row: sqlite3.Row) -> dict[str, Any]:
    """Map a goal_drafts row into GoalDraftRecord kwargs."""
    return {
        "id": row["id"],
        "discovery_session_id": row["discovery_session_id"],
        "goal_id": row["goal_id"],
        "status": row["status"],
        "contract": json_loads(row["contract_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_pause_record(row: sqlite3.Row) -> dict[str, Any]:
    """Map a pause_records row into PauseRecord kwargs."""
    return {
        "id": row["id"],
        "loop_run_id": row["loop_run_id"],
        "session_id": row["session_id"],
        "iteration_id": row["iteration_id"],
        "task_id": row["task_id"],
        "reason": row["reason"],
        "question": row["question"],
        "requested_input": row["requested_input"],
        "resume_mode": row["resume_mode"],
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_resume_event(row: sqlite3.Row) -> dict[str, Any]:
    """Map a resume_events row into ResumeEventRecord kwargs."""
    return {
        "id": row["id"],
        "pause_id": row["pause_id"],
        "loop_run_id": row["loop_run_id"],
        "session_id": row["session_id"],
        "message": row["message"],
        "action": row["action"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_provider_profile(row: sqlite3.Row) -> dict[str, Any]:
    """Map a provider_profiles row into ProviderProfileRecord kwargs."""
    return {
        "id": row["id"],
        "provider": row["provider"],
        "label": row["label"],
        "credential_ref": row["credential_ref"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_provider_run(row: sqlite3.Row) -> dict[str, Any]:
    """Map a provider_runs row into ProviderRunRecord kwargs."""
    keys = row.keys()
    return {
        "id": row["id"],
        "provider": row["provider"],
        "provider_profile_id": row["provider_profile_id"]
        if "provider_profile_id" in keys
        else None,
        "provider_session_id": row["provider_session_id"]
        if "provider_session_id" in keys
        else None,
        "session_id": row["session_id"],
        "loop_run_id": row["loop_run_id"],
        "iteration_id": row["iteration_id"],
        "role": row["role"],
        "status": row["status"],
        "request": json_loads(row["request_json"]),
        "response": json_loads(row["response_json"]),
        "error_kind": row["error_kind"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_provider_session(row: sqlite3.Row) -> dict[str, Any]:
    """Map a provider_sessions row into ProviderSessionRecord kwargs."""
    return {
        "id": row["id"],
        "provider_profile_id": row["provider_profile_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_quota_state(row: sqlite3.Row) -> dict[str, Any]:
    """Map a quota_state row into QuotaStateRecord kwargs."""
    return {
        "id": row["id"],
        "provider_profile_id": row["provider_profile_id"],
        "status": row["status"],
        "reason": row["reason"],
        "observed_at": row["observed_at"],
        "reset_at": row["reset_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_context_package(row: sqlite3.Row) -> dict[str, Any]:
    """Map a context_packages row into ContextPackageRecord kwargs."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "loop_run_id": row["loop_run_id"],
        "iteration_id": row["iteration_id"],
        "role": row["role"],
        "task_id": row["task_id"],
        "package": json_loads(row["package_json"]),
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_role_instance(row: sqlite3.Row) -> dict[str, Any]:
    """Map a role_instances row into RoleInstanceRecord kwargs."""
    return {
        "id": row["id"],
        "role": row["role"],
        "label": row["label"],
        "status": row["status"],
        "capabilities": json_loads(row["capabilities_json"]),
        "current_session_id": row["current_session_id"],
        "current_goal_id": row["current_goal_id"],
        "last_used_at": row["last_used_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_role_provider_binding(row: sqlite3.Row) -> dict[str, Any]:
    """Map a role_provider_bindings row into RoleProviderBindingRecord kwargs."""
    return {
        "id": row["id"],
        "role_instance_id": row["role_instance_id"],
        "provider_profile_id": row["provider_profile_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_work_item(row: sqlite3.Row) -> dict[str, Any]:
    """Map a work_items row into WorkItemRecord kwargs."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "goal_id": row["goal_id"],
        "goal_revision_id": row["goal_revision_id"],
        "kind": row["kind"],
        "required_role": row["required_role"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_assignment(row: sqlite3.Row) -> dict[str, Any]:
    """Map an assignments row into AssignmentRecord kwargs."""
    return {
        "id": row["id"],
        "work_item_id": row["work_item_id"],
        "role_instance_id": row["role_instance_id"],
        "session_id": row["session_id"],
        "goal_id": row["goal_id"],
        "status": row["status"],
        "assigned_at": row["assigned_at"],
        "completed_at": row["completed_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_approval_request(row: sqlite3.Row) -> dict[str, Any]:
    """Map an approval_requests row into ApprovalRequestRecord kwargs."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "kind": row["kind"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "requested_by": row["requested_by"],
        "scope": json_loads(row["scope_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def _map_approval_decision(row: sqlite3.Row) -> dict[str, Any]:
    """Map an approval_decisions row into ApprovalDecisionRecord kwargs."""
    return {
        "id": row["id"],
        "approval_request_id": row["approval_request_id"],
        "decision": row["decision"],
        "decided_by": row["decided_by"],
        "message": row["message"],
        "created_at": row["created_at"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_latest_discovery_session(
    connection: sqlite3.Connection, project_root: str
) -> DiscoverySessionRecord | None:
    """Load the latest discovery session for a project root."""
    return fetch_one(
        connection,
        "select * from discovery_sessions where project_root = ? order by updated_at desc, id desc limit 1",
        (project_root,),
        DiscoverySessionRecord,
        _map_discovery_session,
    )


def load_discussion_turns(
    connection: sqlite3.Connection, discovery_session_id: str
) -> list[DiscussionTurnRecord]:
    """Load discussion turns for a discovery session."""
    return fetch_many(
        connection,
        "select * from discussion_turns where discovery_session_id = ? order by created_at, id",
        (discovery_session_id,),
        DiscussionTurnRecord,
        _map_discussion_turn,
    )


def load_goal_draft_for_discovery(
    connection: sqlite3.Connection, discovery_session_id: str
) -> GoalDraftRecord | None:
    """Load the latest durable goal draft for one discovery session."""
    return fetch_one(
        connection,
        """
        select * from goal_drafts
        where discovery_session_id = ?
        order by updated_at desc, id desc
        limit 1
        """,
        (discovery_session_id,),
        GoalDraftRecord,
        _map_goal_draft,
    )


def load_latest_pause_record(
    connection: sqlite3.Connection, loop_run_id: str | None = None
) -> PauseRecord | None:
    """Load the latest open pause record."""
    if loop_run_id is None:
        return fetch_one(
            connection,
            "select * from pause_records where status = 'open' order by created_at desc, id desc limit 1",
            (),
            PauseRecord,
            _map_pause_record,
        )

    return fetch_one(
        connection,
        "select * from pause_records where loop_run_id = ? and status = 'open' order by created_at desc, id desc limit 1",
        (loop_run_id,),
        PauseRecord,
        _map_pause_record,
    )


def load_pause_records_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[PauseRecord]:
    """Load pause records for a loop run."""
    return fetch_many(
        connection,
        "select * from pause_records where loop_run_id = ? order by created_at, id",
        (loop_run_id,),
        PauseRecord,
        _map_pause_record,
    )


def load_resume_events_for_pause(
    connection: sqlite3.Connection, pause_id: str
) -> list[ResumeEventRecord]:
    """Load resume events for a pause."""
    return fetch_many(
        connection,
        "select * from resume_events where pause_id = ? order by created_at, id",
        (pause_id,),
        ResumeEventRecord,
        _map_resume_event,
    )


def load_provider_profile(
    connection: sqlite3.Connection, profile_id: str
) -> ProviderProfileRecord | None:
    """Load one provider profile by id."""
    return fetch_one(
        connection,
        "select * from provider_profiles where id = ?",
        (profile_id,),
        ProviderProfileRecord,
        _map_provider_profile,
    )


def load_provider_profiles(connection: sqlite3.Connection) -> list[ProviderProfileRecord]:
    """Load configured provider profiles in stable display order."""
    return fetch_many(
        connection,
        "select * from provider_profiles order by provider, id",
        (),
        ProviderProfileRecord,
        _map_provider_profile,
    )


def load_provider_runs_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[ProviderRunRecord]:
    """Load provider runs for a loop run."""
    return fetch_many(
        connection,
        "select * from provider_runs where loop_run_id = ? order by created_at, id",
        (loop_run_id,),
        ProviderRunRecord,
        _map_provider_run,
    )


def load_active_provider_session(
    connection: sqlite3.Connection, profile_id: str
) -> ProviderSessionRecord | None:
    """Load the latest active provider session for one profile."""
    return fetch_one(
        connection,
        """
        select * from provider_sessions
        where provider_profile_id = ? and status = 'active'
        order by started_at desc, id desc
        limit 1
        """,
        (profile_id,),
        ProviderSessionRecord,
        _map_provider_session,
    )


def load_quota_state_for_profile(
    connection: sqlite3.Connection, profile_id: str
) -> QuotaStateRecord | None:
    """Load the latest observed quota state for one provider profile."""
    return fetch_one(
        connection,
        """
        select * from quota_state
        where provider_profile_id = ?
        order by observed_at desc, id desc
        limit 1
        """,
        (profile_id,),
        QuotaStateRecord,
        _map_quota_state,
    )


def load_context_packages_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[ContextPackageRecord]:
    """Load context packages for a loop run."""
    return fetch_many(
        connection,
        "select * from context_packages where loop_run_id = ? order by created_at, id",
        (loop_run_id,),
        ContextPackageRecord,
        _map_context_package,
    )


def load_role_instances(connection: sqlite3.Connection) -> list[RoleInstanceRecord]:
    """Load durable role instances in stable display order."""
    return fetch_many(
        connection,
        "select * from role_instances order by role, id",
        (),
        RoleInstanceRecord,
        _map_role_instance,
    )


def load_role_provider_bindings(
    connection: sqlite3.Connection,
) -> list[RoleProviderBindingRecord]:
    """Load role provider bindings in stable display order."""
    return fetch_many(
        connection,
        "select * from role_provider_bindings order by role_instance_id, created_at, id",
        (),
        RoleProviderBindingRecord,
        _map_role_provider_binding,
    )


def load_provider_binding_for_role(
    connection: sqlite3.Connection, role_instance_id: str
) -> RoleProviderBindingRecord | None:
    """Load the active provider profile binding for one role instance."""
    return fetch_one(
        connection,
        """
        select * from role_provider_bindings
        where role_instance_id = ? and status = 'active'
        order by updated_at desc, id desc
        limit 1
        """,
        (role_instance_id,),
        RoleProviderBindingRecord,
        _map_role_provider_binding,
    )


def load_idle_role_instances(
    connection: sqlite3.Connection, role: str
) -> list[RoleInstanceRecord]:
    """Load idle role instances using LRU-ish order."""
    return fetch_many(
        connection,
        """
        select * from role_instances
        where role = ? and status = 'idle'
        order by coalesce(last_used_at, '0000-01-01T00:00:00+00:00'), updated_at, id
        """,
        (role,),
        RoleInstanceRecord,
        _map_role_instance,
    )


def load_work_items(connection: sqlite3.Connection) -> list[WorkItemRecord]:
    """Load durable work items in queue display order."""
    return fetch_many(
        connection,
        "select * from work_items order by priority, created_at, id",
        (),
        WorkItemRecord,
        _map_work_item,
    )


def load_pending_work_items(connection: sqlite3.Connection) -> list[WorkItemRecord]:
    """Load pending work items in scheduler order."""
    return fetch_many(
        connection,
        """
        select * from work_items
        where status = 'pending'
        order by priority, created_at, id
        """,
        (),
        WorkItemRecord,
        _map_work_item,
    )


def load_work_item(
    connection: sqlite3.Connection, work_item_id: str
) -> WorkItemRecord | None:
    """Load one durable work item by id."""
    return fetch_one(
        connection,
        "select * from work_items where id = ?",
        (work_item_id,),
        WorkItemRecord,
        _map_work_item,
    )


def load_assignments(connection: sqlite3.Connection) -> list[AssignmentRecord]:
    """Load durable assignments in assignment order."""
    return fetch_many(
        connection,
        "select * from assignments order by assigned_at, id",
        (),
        AssignmentRecord,
        _map_assignment,
    )


def load_approval_requests(connection: sqlite3.Connection) -> list[ApprovalRequestRecord]:
    """Load scoped approval requests in display order."""
    return fetch_many(
        connection,
        "select * from approval_requests order by created_at, id",
        (),
        ApprovalRequestRecord,
        _map_approval_request,
    )


def load_approval_decisions(
    connection: sqlite3.Connection, approval_request_id: str
) -> list[ApprovalDecisionRecord]:
    """Load decisions for one approval request."""
    return fetch_many(
        connection,
        "select * from approval_decisions where approval_request_id = ? order by created_at, id",
        (approval_request_id,),
        ApprovalDecisionRecord,
        _map_approval_decision,
    )

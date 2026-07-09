"""Render user-facing runtime workbench views."""

import sqlite3

from curator.core.enums import AssignmentStatus, ProviderProfileStatus
from curator.core.schema import ProviderProfileRecord, RoleInstanceRecord
from curator.providers.detect import provider_setup_hint
from curator.state.repositories import (
    load_approval_requests,
    load_assignments,
    load_evidence_refs_for_run,
    load_latest_goal_run,
    load_latest_pause_record,
    load_latest_session,
    load_loop_runs_for_session,
    load_memory_entries,
    load_provider_binding_for_role,
    load_provider_profile,
    load_provider_profiles,
    load_provider_runs_for_run,
    load_quota_state_for_profile,
    load_role_provider_bindings,
    load_role_instances,
    load_work_item,
    load_work_items,
)


def _quota_status(connection: sqlite3.Connection, provider_profile_id: str) -> str:
    """Return the display quota status for one provider profile."""
    quota = load_quota_state_for_profile(connection, provider_profile_id)
    return quota.status.value if quota else "unknown"


def _bound_agent_ids(connection: sqlite3.Connection, provider_profile_id: str) -> list[str]:
    """Return active agent ids bound to one provider profile."""
    return [
        binding.role_instance_id
        for binding in load_role_provider_bindings(connection)
        if binding.status.value == "active"
        and binding.provider_profile_id == provider_profile_id
    ]


def _active_profiles(connection: sqlite3.Connection) -> list[ProviderProfileRecord]:
    """Return active provider profiles in display order."""
    return [
        profile
        for profile in load_provider_profiles(connection)
        if profile.status is ProviderProfileStatus.ACTIVE
    ]


def _preferred_profile(
    connection: sqlite3.Connection,
    profiles: list[ProviderProfileRecord],
) -> ProviderProfileRecord | None:
    """Return the best default profile for a suggested manual action."""
    if not profiles:
        return None

    return sorted(
        profiles,
        key=lambda profile: (
            _quota_status(connection, profile.id) == "unknown",
            profile.id,
        ),
    )[0]


def _bound_profile(
    connection: sqlite3.Connection, role_instance_id: str
) -> ProviderProfileRecord | None:
    """Return the active provider profile for a role instance."""
    binding = load_provider_binding_for_role(connection, role_instance_id)
    if binding is None:
        return None
    return load_provider_profile(connection, binding.provider_profile_id)


def _current_work(connection: sqlite3.Connection, role_instance_id: str) -> str:
    """Return the current active work item id for a role instance."""
    for assignment in load_assignments(connection):
        if (
            assignment.role_instance_id == role_instance_id
            and assignment.status is AssignmentStatus.ACTIVE
        ):
            item = load_work_item(connection, assignment.work_item_id)
            return item.id if item else assignment.work_item_id
    return "none"


def _next_agent_action(connection: sqlite3.Connection, role: RoleInstanceRecord) -> str:
    """Return the next useful manual provider command for one role instance."""
    profiles = _active_profiles(connection)
    if not profiles:
        return "none"

    bound_profile = _bound_profile(connection, role.id)
    if bound_profile is None:
        profile = _preferred_profile(connection, profiles)
        return f"/agent bind {role.id} {profile.id}" if profile else "none"

    alternatives = [profile for profile in profiles if profile.id != bound_profile.id]
    profile = _preferred_profile(connection, alternatives)
    return f"/agent switch {role.id} {profile.id}" if profile else "none"


def _agent_line(connection: sqlite3.Connection, role: RoleInstanceRecord) -> str:
    """Return one runtime-first agent display line."""
    profile = _bound_profile(connection, role.id)
    provider_id = profile.id if profile else "none"
    quota = _quota_status(connection, profile.id) if profile else "n/a"
    work = _current_work(connection, role.id)
    action = _next_agent_action(connection, role)
    return (
        f"- {role.id} {role.role.value} {role.status.value} "
        f"provider={provider_id} quota={quota} work={work} next={action}"
    )


def render_agents(connection: sqlite3.Connection) -> str:
    """Render role pool instances for terminal users."""
    lines = ["Agents:"]
    roles = load_role_instances(connection)
    if not roles:
        return "Agents:\n- none"
    for role in roles:
        lines.append(_agent_line(connection, role))
    return "\n".join(lines)


def render_providers(connection: sqlite3.Connection) -> str:
    """Render provider profiles, quota state, and active role bindings."""
    lines = ["Providers:"]
    profiles = load_provider_profiles(connection)
    if not profiles:
        return "Providers:\n- none"
    for profile in profiles:
        quota = _quota_status(connection, profile.id)
        bound_agents = _bound_agent_ids(connection, profile.id)
        bound = ",".join(bound_agents) if bound_agents else "none"
        lines.append(
            f"- {profile.id} {profile.provider.value} {profile.status.value} "
            f"quota={quota} bound={bound} credential={profile.credential_ref}"
        )
    return "\n".join(lines)


def render_runtime_summary(connection: sqlite3.Connection) -> str:
    """Render the current runtime session and loop summary."""
    session = load_latest_session(connection)
    if session is None:
        return "\n".join(["Runtime:", "- Session: none", "- Loop: none", "- Status: idle"])

    loop_runs = load_loop_runs_for_session(connection, session.id)
    loop_run = loop_runs[-1] if loop_runs else None
    loop_id = loop_run.id if loop_run else "none"
    status = loop_run.status.value if loop_run else session.status
    return "\n".join(
        [
            "Runtime:",
            f"- Session: {session.id}",
            f"- Loop: {loop_id}",
            f"- Status: {status}",
        ]
    )


def render_evidence(connection: sqlite3.Connection) -> str:
    """Render evidence refs for the latest loop run."""
    session = load_latest_session(connection)
    if session is None:
        return "Evidence:\n- none"

    loop_runs = load_loop_runs_for_session(connection, session.id)
    if not loop_runs:
        return "Evidence:\n- none"

    evidence_refs = load_evidence_refs_for_run(connection, loop_runs[-1].id)
    if not evidence_refs:
        return "Evidence:\n- none"

    lines = ["Evidence:"]
    for evidence in evidence_refs[-5:]:
        lines.append(f"- {evidence.kind.value}: {evidence.summary}")
    return "\n".join(lines)


def render_events(connection: sqlite3.Connection) -> str:
    """Render recent runtime provider and evidence events."""
    session = load_latest_session(connection)
    if session is None:
        return "Events:\n- none"

    loop_runs = load_loop_runs_for_session(connection, session.id)
    if not loop_runs:
        return "Events:\n- none"

    loop_run = loop_runs[-1]
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)
    evidence_refs = load_evidence_refs_for_run(connection, loop_run.id)
    lines = ["Events:"]
    for run in provider_runs[-3:]:
        profile = run.provider_profile_id or run.provider.value
        lines.append(f"- provider {run.role.value} {run.status.value} via {profile}")
    for evidence in evidence_refs[-3:]:
        lines.append(f"- evidence {evidence.kind.value} saved by {evidence.producer_role.value}")
    return "\n".join(lines) if len(lines) > 1 else "Events:\n- none"


def render_next_actions(connection: sqlite3.Connection) -> str:
    """Render suggested manual commands for users to choose from."""
    actions = []
    for role in load_role_instances(connection):
        action = _next_agent_action(connection, role)
        if action != "none":
            actions.append(action)

    if not _active_profiles(connection):
        actions.append(provider_setup_hint())
    if load_latest_goal_run(connection) is None:
        actions.append("Type what you want to work on to start a goal")

    if not actions:
        actions.append("Type what you want to work on, or /help for tasks")

    lines = ["Next Actions:"]
    lines.extend(f"- {action}" for action in actions[:6])
    return "\n".join(lines)


def render_agent_status(connection: sqlite3.Connection, role_instance_id: str) -> str:
    """Render detailed provider state and choices for one agent."""
    role = next(
        (candidate for candidate in load_role_instances(connection) if candidate.id == role_instance_id),
        None,
    )
    if role is None:
        return f"Unknown agent: {role_instance_id}"

    profile = _bound_profile(connection, role.id)
    quota = _quota_status(connection, profile.id) if profile else "n/a"
    credential = profile.credential_ref if profile else "none"
    provider_id = profile.id if profile else "none"
    lines = [
        f"Agent: {role.id}",
        f"Role: {role.role.value}",
        f"State: {role.status.value}",
        f"Provider: {provider_id}",
        f"Quota: {quota}",
        f"Credential: {credential}",
        f"Current work: {_current_work(connection, role.id)}",
        "",
        "Available profiles:",
    ]
    profiles = load_provider_profiles(connection)
    if not profiles:
        lines.append("- none")
    else:
        for candidate in profiles:
            marker = " current" if profile and candidate.id == profile.id else ""
            lines.append(
                f"- {candidate.id} {candidate.provider.value} "
                f"quota={_quota_status(connection, candidate.id)}{marker}"
            )
    action = _next_agent_action(connection, role)
    lines.extend(["", "Actions:", f"- {action}" if action != "none" else "- none"])
    return "\n".join(lines)


def render_queue(connection: sqlite3.Connection) -> str:
    """Render queued and assigned work items for terminal users."""
    lines = ["Queue:"]
    work_items = load_work_items(connection)
    assignments = {assignment.work_item_id: assignment for assignment in load_assignments(connection)}
    if not work_items:
        return "Queue:\n- none"
    for item in work_items:
        assigned = assignments.get(item.id)
        suffix = f" -> {assigned.role_instance_id}" if assigned else ""
        lines.append(
            f"- {item.id} [{item.status.value}] {item.required_role.value}: {item.title}{suffix}"
        )
    return "\n".join(lines)


def render_approvals(connection: sqlite3.Connection) -> str:
    """Render scoped approval requests for terminal users."""
    lines = ["Approvals:"]
    approvals = load_approval_requests(connection)
    if not approvals:
        return "Approvals:\n- none"
    for approval in approvals:
        lines.append(
            f"- {approval.id} [{approval.status.value}] {approval.kind.value}: {approval.title}"
        )
    return "\n".join(lines)


def render_memory(connection: sqlite3.Connection, limit: int = 10) -> str:
    """Render distilled runtime memory lessons for terminal users."""
    session = load_latest_session(connection)
    scope = str(session.project_root) if session is not None else None
    entries = load_memory_entries(connection, scope, limit=limit) if scope else []
    if not entries:
        return (
            "Memory:\n- none yet — Curator records lessons when loops fail or pause."
        )

    lines = ["Memory:"]
    for entry in entries:
        role = entry.role.value if entry.role else "shared"
        lines.append(f"- [{entry.kind}] {role}: {entry.summary} (source: {entry.source_ref})")
    return "\n".join(lines)


def render_paused_state(connection: sqlite3.Connection) -> str:
    """Render the latest pause cursor for terminal users."""
    pause = load_latest_pause_record(connection)
    if pause is None:
        return "Paused:\n- none"
    return "\n".join(
        [
            "Paused:",
            f"- Reason: {pause.reason}",
            f"- Question: {pause.question}",
            f"- Requested input: {pause.requested_input}",
            "- Next: /node current or /resume <message>",
        ]
    )


def render_workbench(connection: sqlite3.Connection) -> str:
    """Render the combined Runtime Workspace view."""
    return "\n\n".join(
        [
            "Agent Runtime Workspace",
            render_runtime_summary(connection),
            render_agents(connection),
            render_providers(connection),
            render_queue(connection),
            render_approvals(connection),
            render_evidence(connection),
            render_events(connection),
            render_memory(connection, limit=3),
            render_paused_state(connection),
            render_next_actions(connection),
        ]
    )

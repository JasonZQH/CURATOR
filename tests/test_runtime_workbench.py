"""Verify multi-agent runtime queues, approvals, and workbench shell UX."""

from datetime import UTC, datetime, timedelta

from curator.core.enums import (
    ApprovalKind,
    ApprovalStatus,
    AssignmentStatus,
    ProviderBindingStatus,
    ProviderName,
    ProviderProfileStatus,
    QuotaStatus,
    RoleInstanceStatus,
    RoleName,
    WorkItemKind,
    WorkItemStatus,
)
from curator.core.paths import build_curator_paths
from curator.core.schema import (
    ApprovalRequestRecord,
    ProviderProfileRecord,
    QuotaStateRecord,
    RoleInstanceRecord,
    WorkItemRecord,
)
from curator.runtime.queue import enqueue_followup_qa_work, tick_work_queue
from curator.runtime.action_policy import ActionPolicy, ActionRequest, ActionType
from curator.shell.repl import ShellState, handle_shell_input
from curator.state.db import connect_database, initialize_database
from fakes import enable_live_mode, install_fake_claude
from curator.state.repositories import (
    insert_approval_request,
    insert_provider_profile,
    insert_quota_state,
    insert_role_instance,
    insert_work_item,
    load_approval_decisions,
    load_approval_requests,
    load_assignments,
    load_provider_binding_for_role,
    load_role_instances,
    load_work_items,
)


def _connection(tmp_path):
    """Open an initialized Curator database for a temporary project."""
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    return connection


def test_queue_tick_assigns_oldest_idle_matching_role_without_tasks(tmp_path):
    """Verify role pool scheduling is independent from legacy task rows."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer-newer",
                role=RoleName.ENGINEER,
                label="Engineer newer",
                status=RoleInstanceStatus.IDLE,
                capabilities=["python"],
                last_used_at=now - timedelta(minutes=5),
                created_at=now,
                updated_at=now,
            ),
        )
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer-older",
                role=RoleName.ENGINEER,
                label="Engineer older",
                status=RoleInstanceStatus.IDLE,
                capabilities=["python"],
                last_used_at=now - timedelta(hours=2),
                created_at=now,
                updated_at=now,
            ),
        )
        insert_work_item(
            connection,
            WorkItemRecord(
                id="work-impl-1",
                session_id="session-router",
                goal_id="goal-1",
                kind=WorkItemKind.IMPLEMENTATION,
                required_role=RoleName.ENGINEER,
                title="Implement login layout",
                description="Use current goal context.",
                status=WorkItemStatus.PENDING,
                created_at=now,
                updated_at=now,
            ),
        )

        decisions = tick_work_queue(connection, now=now)
        roles = {role.id: role for role in load_role_instances(connection)}
        work_items = load_work_items(connection)
        assignments = load_assignments(connection)
        task_count = connection.execute("select count(*) from tasks").fetchone()[0]
    finally:
        connection.close()

    assert decisions == ["assigned work-impl-1 to engineer-older"]
    assert roles["engineer-older"].status is RoleInstanceStatus.BUSY
    assert roles["engineer-newer"].status is RoleInstanceStatus.IDLE
    assert work_items[0].status is WorkItemStatus.ASSIGNED
    assert assignments[0].role_instance_id == "engineer-older"
    assert assignments[0].status is AssignmentStatus.ACTIVE
    assert task_count == 0


def test_queue_leaves_work_pending_when_all_matching_roles_busy(tmp_path):
    """Verify queued work remains visible when no matching role is idle."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="qa-busy",
                role=RoleName.QA,
                label="QA busy",
                status=RoleInstanceStatus.BUSY,
                capabilities=[],
                current_session_id="session-a",
                current_goal_id="goal-a",
                last_used_at=now,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_work_item(
            connection,
            WorkItemRecord(
                id="work-qa-1",
                session_id="session-router",
                goal_id="goal-1",
                kind=WorkItemKind.VALIDATION,
                required_role=RoleName.QA,
                title="Validate login layout",
                description="Run QA validation.",
                status=WorkItemStatus.PENDING,
                created_at=now,
                updated_at=now,
            ),
        )

        decisions = tick_work_queue(connection, now=now)
        work_items = load_work_items(connection)
        assignments = load_assignments(connection)
    finally:
        connection.close()

    assert decisions == ["queued work-qa-1 waiting for idle qa"]
    assert work_items[0].status is WorkItemStatus.PENDING
    assert assignments == []


def test_engineer_completion_enqueues_qa_followup_work(tmp_path):
    """Verify implementation completion can create queued QA work."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_work_item(
            connection,
            WorkItemRecord(
                id="work-impl-1",
                session_id="session-router",
                goal_id="goal-1",
                kind=WorkItemKind.IMPLEMENTATION,
                required_role=RoleName.ENGINEER,
                title="Implement login layout",
                description="Use current goal context.",
                status=WorkItemStatus.DONE,
                created_at=now,
                updated_at=now,
            ),
        )

        qa_work = enqueue_followup_qa_work(connection, "work-impl-1", now=now)
        work_items = load_work_items(connection)
    finally:
        connection.close()

    assert qa_work.id == "work-impl-1-qa"
    assert qa_work.required_role is RoleName.QA
    assert qa_work.status is WorkItemStatus.PENDING
    assert [item.id for item in work_items] == ["work-impl-1", "work-impl-1-qa"]


def test_approvals_are_scoped_runtime_records_not_timeline_messages(tmp_path):
    """Verify approvals persist separately from messages and events."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_approval_request(
            connection,
            ApprovalRequestRecord(
                id="approval-plan-1",
                session_id="session-router",
                kind=ApprovalKind.PLAN,
                title="Approve plan",
                description="PM proposed a plan for goal-1.",
                status=ApprovalStatus.PENDING,
                requested_by="pm.goal-owner.1",
                scope={"goal_id": "goal-1", "revision": 1},
                created_at=now,
                updated_at=now,
            ),
        )

        approvals = load_approval_requests(connection)
        message_count = connection.execute("select count(*) from messages").fetchone()[0]
        event_count = connection.execute("select count(*) from events").fetchone()[0]
    finally:
        connection.close()

    assert approvals[0].kind is ApprovalKind.PLAN
    assert approvals[0].status is ApprovalStatus.PENDING
    assert approvals[0].scope == {"goal_id": "goal-1", "revision": 1}
    assert message_count == 0
    assert event_count == 0


def test_goal_acceptance_writes_scoped_approval_ledger(tmp_path, monkeypatch):
    """Verify yes acts as explicit approval while preserving shell acceptance flow."""
    enable_live_mode(tmp_path)
    install_fake_claude(tmp_path, monkeypatch)
    state = ShellState(project_root=tmp_path, gate_mode=True)

    handle_shell_input(state, "Fix mobile login layout")
    accept = handle_shell_input(state, "yes")

    connection = _connection(tmp_path)
    try:
        approvals = load_approval_requests(connection)
        decisions = load_approval_decisions(connection, approvals[0].id)
    finally:
        connection.close()

    assert "Goal accepted:" in accept.text
    assert approvals[0].kind is ApprovalKind.GOAL
    assert approvals[0].status is ApprovalStatus.APPROVED
    assert decisions[0].decision is ApprovalStatus.APPROVED
    assert approvals[0].scope["goal_id"] == "goal-fix-mobile-login-layout"


def test_shell_approve_and_reject_update_scoped_approval_state(tmp_path):
    """Verify approval commands update durable approval requests."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_approval_request(
            connection,
            ApprovalRequestRecord(
                id="approval-permission-1",
                session_id="session-router",
                kind=ApprovalKind.PERMISSION,
                title="Allow file write",
                description="Engineer requested a scoped write.",
                status=ApprovalStatus.PENDING,
                requested_by="engineer.1",
                scope={"path": "src/example.py"},
                created_at=now,
                updated_at=now,
            ),
        )
        insert_approval_request(
            connection,
            ApprovalRequestRecord(
                id="approval-plan-2",
                session_id="session-router",
                kind=ApprovalKind.PLAN,
                title="Approve plan",
                description="PM requested plan approval.",
                status=ApprovalStatus.PENDING,
                requested_by="pm.goal-owner.1",
                scope={"goal_id": "goal-2"},
                created_at=now,
                updated_at=now,
            ),
        )
    finally:
        connection.close()

    approved = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/approve approval-permission-1 allow only this file",
    )
    rejected = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/reject approval-plan-2 too broad",
    )

    connection = _connection(tmp_path)
    try:
        approvals = {approval.id: approval for approval in load_approval_requests(connection)}
        approve_decisions = load_approval_decisions(connection, "approval-permission-1")
        reject_decisions = load_approval_decisions(connection, "approval-plan-2")
    finally:
        connection.close()

    assert "approved approval-permission-1" in approved.text
    assert "rejected approval-plan-2" in rejected.text
    assert approvals["approval-permission-1"].status is ApprovalStatus.APPROVED
    assert approvals["approval-plan-2"].status is ApprovalStatus.REJECTED
    assert approve_decisions[0].message == "allow only this file"
    assert reject_decisions[0].message == "too broad"


def test_workbench_shell_renders_agents_queue_approvals_and_tick(tmp_path):
    """Verify terminal workbench commands are user-readable after restart."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="pm.coordinator",
                role=RoleName.PM,
                label="PM coordinator",
                status=RoleInstanceStatus.IDLE,
                capabilities=["routing"],
                created_at=now,
                updated_at=now,
            ),
        )
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer.1",
                role=RoleName.ENGINEER,
                label="Engineer 1",
                status=RoleInstanceStatus.IDLE,
                capabilities=["python"],
                last_used_at=now - timedelta(hours=1),
                created_at=now,
                updated_at=now,
            ),
        )
        insert_work_item(
            connection,
            WorkItemRecord(
                id="work-impl-1",
                session_id="session-router",
                goal_id="goal-1",
                kind=WorkItemKind.IMPLEMENTATION,
                required_role=RoleName.ENGINEER,
                title="Implement login layout",
                description="Use current goal context.",
                status=WorkItemStatus.PENDING,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_approval_request(
            connection,
            ApprovalRequestRecord(
                id="approval-plan-1",
                session_id="session-router",
                kind=ApprovalKind.PLAN,
                title="Approve plan",
                description="PM proposed a plan for goal-1.",
                status=ApprovalStatus.PENDING,
                requested_by="pm.goal-owner.1",
                scope={"goal_id": "goal-1"},
                created_at=now,
                updated_at=now,
            ),
        )
    finally:
        connection.close()

    tick = handle_shell_input(ShellState(project_root=tmp_path), "/queue tick")
    workbench = handle_shell_input(ShellState(project_root=tmp_path), "/workbench")
    agents = handle_shell_input(ShellState(project_root=tmp_path), "/agents")
    queue = handle_shell_input(ShellState(project_root=tmp_path), "/queue")
    approvals = handle_shell_input(ShellState(project_root=tmp_path), "/approvals")

    assert "assigned work-impl-1 to engineer.1" in tick.text
    assert "Agent Runtime Workspace" in workbench.text
    assert "engineer.1" in workbench.text
    assert "work-impl-1" in workbench.text
    assert "approval-plan-1" in workbench.text
    assert "Runtime:" in workbench.text
    assert "Providers:" in workbench.text
    assert "Evidence:" in workbench.text
    assert "Next Actions:" in workbench.text
    assert "Agents:" in agents.text
    assert "Queue:" in queue.text
    assert "assigned" in queue.text
    assert "Approvals:" in approvals.text
    assert "Approve plan" in approvals.text


def test_shell_renders_providers_and_switches_agent_bindings(tmp_path):
    """Verify provider profile commands render and switch active bindings."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer.1",
                role=RoleName.ENGINEER,
                label="Engineer 1",
                status=RoleInstanceStatus.IDLE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="codex-work",
                provider=ProviderName.CODEX,
                label="Codex work",
                credential_ref="env:CODEX_WORK",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="claude-team",
                provider=ProviderName.CLAUDE_CODE,
                label="Claude team",
                credential_ref="keychain:claude-team",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_quota_state(
            connection,
            QuotaStateRecord(
                id="quota-codex-work",
                provider_profile_id="codex-work",
                status=QuotaStatus.LIMITED,
                reason="manual check",
                observed_at=now,
            ),
        )
    finally:
        connection.close()

    providers_before = handle_shell_input(ShellState(project_root=tmp_path), "/providers")
    bind = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/agent bind engineer.1 codex-work",
    )
    agents = handle_shell_input(ShellState(project_root=tmp_path), "/agents")
    providers_after = handle_shell_input(ShellState(project_root=tmp_path), "/providers")
    switch = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/agent switch engineer.1 claude-team",
    )

    connection = _connection(tmp_path)
    try:
        active_binding = load_provider_binding_for_role(connection, "engineer.1")
    finally:
        connection.close()

    assert "codex-work codex active quota=limited bound=none" in providers_before.text
    assert "claude-team claude-code active quota=unknown bound=none" in providers_before.text
    assert "Bound engineer.1 to codex-work" in bind.text
    assert "engineer.1 engineer idle provider=codex-work quota=limited" in agents.text
    assert "codex-work codex active quota=limited bound=engineer.1" in providers_after.text
    assert "Switched engineer.1 to claude-team" in switch.text
    assert active_binding is not None
    assert active_binding.provider_profile_id == "claude-team"
    assert active_binding.status is ProviderBindingStatus.ACTIVE


def test_workbench_renders_runtime_first_provider_workspace(tmp_path):
    """Verify the workbench centers runtime state and next provider actions."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer.1",
                role=RoleName.ENGINEER,
                label="Engineer 1",
                status=RoleInstanceStatus.IDLE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer.2",
                role=RoleName.ENGINEER,
                label="Engineer 2",
                status=RoleInstanceStatus.IDLE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="codex-work",
                provider=ProviderName.CODEX,
                label="Codex work",
                credential_ref="env:CODEX_WORK",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="claude-team",
                provider=ProviderName.CLAUDE_CODE,
                label="Claude team",
                credential_ref="keychain:claude-team",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_quota_state(
            connection,
            QuotaStateRecord(
                id="quota-codex-work",
                provider_profile_id="codex-work",
                status=QuotaStatus.LIMITED,
                reason="manual check",
                observed_at=now,
            ),
        )
    finally:
        connection.close()

    handle_shell_input(
        ShellState(project_root=tmp_path),
        "/agent bind engineer.1 codex-work",
    )
    workbench = handle_shell_input(ShellState(project_root=tmp_path), "/workbench")

    assert "Agent Runtime Workspace" in workbench.text
    assert "Runtime:" in workbench.text
    assert "- Session: none" in workbench.text
    assert "Agents:" in workbench.text
    assert "- engineer.1 engineer idle provider=codex-work quota=limited" in workbench.text
    assert "Providers:" in workbench.text
    assert "- codex-work codex active quota=limited bound=engineer.1 credential=env:CODEX_WORK" in workbench.text
    assert "- claude-team claude-code active quota=unknown bound=none credential=keychain:claude-team" in workbench.text
    assert "Evidence:" in workbench.text
    assert "Events:" in workbench.text
    assert "Next Actions:" in workbench.text
    assert "- /agent switch engineer.1 claude-team" in workbench.text
    assert "- /agent bind engineer.2 codex-work" in workbench.text


def test_shell_agent_status_shows_binding_choices_and_actions(tmp_path):
    """Verify agent status gives one agent's provider choices and commands."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    connection = _connection(tmp_path)
    try:
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id="engineer.1",
                role=RoleName.ENGINEER,
                label="Engineer 1",
                status=RoleInstanceStatus.IDLE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="codex-work",
                provider=ProviderName.CODEX,
                label="Codex work",
                credential_ref="env:CODEX_WORK",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="claude-team",
                provider=ProviderName.CLAUDE_CODE,
                label="Claude team",
                credential_ref="keychain:claude-team",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        insert_quota_state(
            connection,
            QuotaStateRecord(
                id="quota-codex-work",
                provider_profile_id="codex-work",
                status=QuotaStatus.LIMITED,
                reason="manual check",
                observed_at=now,
            ),
        )
    finally:
        connection.close()

    bind = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/agent bind engineer.1 codex-work",
    )
    status = handle_shell_input(ShellState(project_root=tmp_path), "/agent status engineer.1")
    missing_arg = handle_shell_input(ShellState(project_root=tmp_path), "/agent status")

    assert "Bound engineer.1 to codex-work" in bind.text
    assert "Agent: engineer.1" in status.text
    assert "Role: engineer" in status.text
    assert "State: idle" in status.text
    assert "Provider: codex-work" in status.text
    assert "Quota: limited" in status.text
    assert "Credential: env:CODEX_WORK" in status.text
    assert "Current work: none" in status.text
    assert "- codex-work codex quota=limited current" in status.text
    assert "- claude-team claude-code quota=unknown" in status.text
    assert "- /agent switch engineer.1 claude-team" in status.text
    assert missing_arg.text == "Usage: /agent status <agent>"


def test_discovery_bootstraps_user_visible_role_pool(tmp_path):
    """Verify first PM discovery makes default role pool visible to users."""
    enable_live_mode(tmp_path)
    state = ShellState(project_root=tmp_path)

    handle_shell_input(state, "Fix mobile login layout")
    agents = handle_shell_input(ShellState(project_root=tmp_path), "/agents")
    workbench = handle_shell_input(ShellState(project_root=tmp_path), "/workbench")

    assert "pm.coordinator" in agents.text
    assert "pm.goal-owner.1" in agents.text
    assert "pm.research.1" in agents.text
    assert "engineer.1" in agents.text
    assert "qa.1" in agents.text
    assert "Agent Runtime Workspace" in workbench.text


def test_action_policy_gate_records_scoped_approval_for_destructive_request(tmp_path):
    """Verify policy gates create durable user approval instead of executing actions."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    policy = ActionPolicy.for_project(tmp_path)
    request = ActionRequest(
        type=ActionType.SHELL_COMMAND,
        command="rm -rf .curator",
        metadata={"work_item_id": "work-impl-1"},
    )

    approval = policy.record_gate(
        _connection(tmp_path),
        request=request,
        session_id="session-router",
        requested_by="engineer.1",
        now=now,
    )
    approvals = handle_shell_input(ShellState(project_root=tmp_path), "/approvals")

    assert approval is not None
    assert approval.kind is ApprovalKind.DESTRUCTIVE_ACTION
    assert approval.status is ApprovalStatus.PENDING
    assert approval.scope["command"] == "rm -rf .curator"
    assert "destructive-action" in approval.id
    assert "Destructive shell command requires approval" in approvals.text


def test_action_policy_gate_records_permission_handoff_for_outside_write(tmp_path):
    """Verify out-of-scope writes become visible permission handoffs."""
    now = datetime(2026, 7, 7, tzinfo=UTC)
    policy = ActionPolicy.for_project(tmp_path)
    request = ActionRequest(type=ActionType.WRITE_FILE, target="/private/etc/passwd")

    approval = policy.record_gate(
        _connection(tmp_path),
        request=request,
        session_id="session-router",
        requested_by="engineer.1",
        now=now,
    )
    workbench = handle_shell_input(ShellState(project_root=tmp_path), "/workbench")

    assert approval is not None
    assert approval.kind is ApprovalKind.PERMISSION
    assert approval.status is ApprovalStatus.PENDING
    assert approval.scope["target"] == "/private/etc/passwd"
    assert "Permission requires user guidance" in workbench.text


def test_next_actions_guides_fresh_project_to_provider_setup(tmp_path):
    """Verify a fresh initialized project always gets a concrete next action."""
    from curator.runtime.workbench import render_next_actions

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)

    rendered = render_next_actions(connection)
    connection.close()

    assert "Next Actions:" in rendered
    assert "- none" not in rendered
    assert "provider add" in rendered
    assert "Type what you want to work on" in rendered

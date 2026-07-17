"""Run the Curator natural-language interactive shell."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from curator.app import (
    resume_goal_loop,
    start_goal_loop,
)
from curator.core.enums import (
    ApprovalKind,
    ApprovalStatus,
    DiscoveryStatus,
    PauseStatus,
    ProviderBindingStatus,
)
from curator.core.paths import build_curator_paths
from curator.core.schema import (
    DiscoverySessionRecord,
    DiscussionTurnRecord,
    GoalContract,
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ResumeEventRecord,
    GoalDraftRecord,
    RoleProviderBindingRecord,
    WorkflowSnapshot,
)
from curator.diagnostics.doctor import inspect_project_health
from curator.diagnostics.preflight import render_preflight, run_preflight
from curator.diagnostics.status import inspect_project_status
from curator.shell.banner import render_banner
from curator.goals.store import accept_goal, propose_goal, save_goal
from curator.nodes.inspection import (
    current_node,
    list_nodes,
    render_node_list,
    render_node_view,
)
from curator.rendering.terminal import (
    render_contract_validation_report,
    render_doctor_report,
    render_status_report,
)
from curator.runtime.queue import tick_work_queue
from curator.runtime.role_pool import ensure_default_role_pool
from curator.runtime.workbench import (
    render_agent_status,
    render_agents,
    render_approvals,
    render_memory,
    render_providers,
    render_queue,
    render_workbench,
)
from curator.providers.events import ProviderEvent, ProviderEventKind
from curator.providers.setup import add_provider_profile
from curator.scheduler.snapshots import load_latest_workflow_snapshot
from curator.shell.intent import detect_cli_command, render_command_hint
from curator.shell.menus import MenuSpec, proposal_menu
from curator.shell.wizard import run_setup_wizard
from curator.shell.onboarding import (
    apply_first_run_init,
    build_welcome_text,
    first_run_needed,
    resolve_mode_for_project,
)
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_approval_decision,
    insert_approval_request,
    insert_discovery_session,
    insert_discussion_turn,
    insert_goal_draft,
    insert_pause_record,
    insert_resume_event,
    insert_role_provider_binding,
    load_approval_requests,
    load_evidence_refs_for_run,
    load_goal_ids,
    load_discussion_turns,
    load_goal_draft_for_discovery,
    load_goal_revision,
    load_latest_discovery_session,
    load_latest_goal_run,
    load_latest_pause_record,
    load_latest_session,
    load_provider_binding_for_role,
    load_provider_profile,
    load_role_instances,
    load_loop_runs_for_session,
    load_sessions_for_project,
)
from curator.runtime.lockfile import ProjectLockedError, project_write_lock
from curator.scheduler.cancellation import CancellationToken
from curator.scheduler.recovery import reconcile_project
from curator.shell.errors import recoverable_error_message
from curator.team.roles import validate_role_contracts
from curator.tui.workflow_panel import render_workflow_lines


@dataclass
class ShellState:
    """Track pending proposals and latest workflow state for a shell session."""

    project_root: Path
    pending_goal: GoalContract | None = None
    latest_snapshot: WorkflowSnapshot | None = None
    should_exit: bool = False
    gate_mode: bool = True
    emit_event: Callable[[ProviderEvent], None] | None = None
    cancellation: CancellationToken = field(default_factory=CancellationToken)


@dataclass(frozen=True)
class ShellResponse:
    """Describe text output and continuation state for one shell input."""

    text: str
    should_exit: bool = False
    menu: MenuSpec | None = None


def _prompt_prefix(state: "ShellState") -> str:
    """Return the mode-aware interactive prompt."""
    mode = resolve_mode_for_project(state.project_root)
    return "(setup) > " if mode.label == "setup" else "> "


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def _database_exists(state: ShellState) -> bool:
    """Return whether the Curator SQLite database exists."""
    return build_curator_paths(state.project_root).database.exists()


def _connect_state(state: ShellState):
    """Open and initialize the Curator state database."""
    connection = connect_database(build_curator_paths(state.project_root).database)
    initialize_database(connection)
    return connection


def _render_goal_proposal(goal: GoalContract, revised: bool = False) -> str:
    """Render a PM goal proposal for user confirmation."""
    lines = [
        "PM drafted a revised goal proposal:" if revised else "PM drafted a goal contract:",
        "",
        "Goal:",
        goal.summary,
        "",
        "Done criteria:",
    ]
    lines.extend(f"- {criterion.description}" for criterion in goal.done_criteria)
    lines.extend(
        [
            "",
            "Constraints:",
            *[f"- {constraint}" for constraint in goal.constraints],
            "",
            "Start this loop? [yes/no/edit <instruction>]",
        ]
    )
    return "\n".join(lines)


def _help_text(full: bool = False) -> str:
    """Return task-oriented shell help, or the full command list."""
    if full:
        return "\n".join(
            [
                "Curator commands:",
                "- /help: show task-oriented help",
                "- /help all: show this full command list",
                "- /setup: guided setup (roles → providers → login)",
                "- /goal current: show current draft or accepted goal",
                "- /goal start: accept and start the saved draft goal",
                "- /goal history: show goal and discovery history",
                "- /node list: show workflow nodes",
                "- /node current: show current workflow node",
                "- /resume <message>: answer the current paused node",
                "- /revise <message>: draft a revised goal from the current pause",
                "- /gate [on|off]: show or toggle proposal review mode",
                "- /cancel: cancel pending proposal or record a cancelled pause",
                "- /history: show discussion and runtime history",
                "- /session current: show the latest durable session",
                "- /workbench: show agents, queue, approvals, and next actions",
                "- /agents: show role pool state",
                "- /providers: show provider profiles, quota, and agent bindings",
                "- /provider add <name>: connect claude-code or codex",
                "- /agent status <agent>: show one agent's provider choices",
                "- /agent bind <agent> <profile>: bind an agent to a provider profile",
                "- /agent switch <agent> <profile>: switch an agent to a provider profile",
                "- /queue: show queued and assigned work",
                "- /queue tick: assign pending work to idle matching agents",
                "- /approvals: show pending user approvals",
                "- /approve <id> [message]: approve one scoped request",
                "- /reject <id> [message]: reject one scoped request",
                "- /evidence: show latest run evidence refs",
                "- /memory: show distilled runtime memory lessons",
                "- /status: show project status",
                "- /doctor: check project health and environment",
                "- /validate: validate role contracts",
                "- /quit: exit",
            ]
        )

    return "\n".join(
        [
            "What do you want to do?",
            "",
            "Start work:",
            "- Type what you want to work on (small requests start immediately)",
            "- /gate on|off — require yes/no/edit review before running",
            "- yes / no / edit <instruction> — answer a pending proposal",
            "",
            "Watch progress:",
            "- /workbench — runtime, agents, queue, approvals, next actions",
            "- /node current — the current workflow node and its evidence",
            "- /evidence — latest run evidence refs",
            "",
            "Handle pauses:",
            "- /resume <answer> — answer the current paused node",
            "- /revise <new scope> — draft a revised goal from the pause",
            "- /cancel — cancel a pending proposal or paused loop",
            "- /approvals, /approve <id>, /reject <id> — scoped approvals",
            "",
            "Configure providers:",
            "- /setup — guided setup (roles → providers → login)",
            "- /provider add claude-code|codex — connect a local provider CLI",
            "- /providers — provider profiles, quota, bindings",
            "- /agents, /agent status <agent> — role pool state",
            "- /agent bind <agent> <profile> — dispatch work to a real provider",
            "",
            "Inspect history:",
            "- /history, /goal history — discussion and goal history",
            "- /memory — distilled lessons from failed or paused runs",
            "- /status, /validate, /session current",
            "",
            "/help all — full command list. /quit — exit.",
        ]
    )


def _apply_goal_edit(goal: GoalContract, instruction: str) -> GoalContract:
    """Return a draft goal updated by one edit instruction.

    `edit summary <text>` rewrites the summary; any other instruction is
    appended as a constraint, matching the original edit grammar.
    """
    cleaned = instruction.strip()
    if not cleaned:
        return goal
    if cleaned.lower().startswith("summary "):
        new_summary = cleaned[len("summary ") :].strip()
        if new_summary:
            return goal.model_copy(update={"summary": new_summary})
        return goal
    return goal.model_copy(update={"constraints": [*goal.constraints, cleaned]})


def _should_gate(state: ShellState, text: str) -> bool:
    """Return whether a request needs the propose/confirm ceremony."""
    return state.gate_mode or "\n" in text or len(text.split()) > 40


# Shell-dialect equivalents for terminal next steps in shared reports.
_SHELL_NEXT_STEPS = {
    "curator provider add claude-code": "/provider add claude-code",
    "curator init": "/init",
    "curator": "Type what you want to work on.",
}


def _handle_status(state: ShellState) -> ShellResponse:
    """Render current project status for the shell."""
    report = inspect_project_status(state.project_root)
    shell_step = _SHELL_NEXT_STEPS.get(report.next_step)
    if shell_step is not None:
        report = replace(report, next_step=shell_step)
    return ShellResponse(render_status_report(report))


def _handle_doctor(state: ShellState) -> ShellResponse:
    """Render project health plus environment preflight for the shell."""
    report = inspect_project_health(state.project_root)
    shell_step = _SHELL_NEXT_STEPS.get(report.recommended_next_step)
    if shell_step is not None:
        report = replace(report, recommended_next_step=shell_step)
    return ShellResponse(
        "\n\n".join(
            [
                render_doctor_report(report),
                render_preflight(run_preflight(state.project_root)),
            ]
        )
    )


def _handle_validate(state: ShellState) -> ShellResponse:
    """Render role contract validation for the shell."""
    paths = build_curator_paths(state.project_root)
    return ShellResponse(render_contract_validation_report(validate_role_contracts(paths)))


def _handle_node_list(state: ShellState) -> ShellResponse:
    """Render nodes for the latest shell workflow snapshot."""
    snapshot = _latest_snapshot(state)
    if snapshot is None:
        return ShellResponse("No nodes yet. Type a natural-language goal first.")
    return ShellResponse(render_node_list(list_nodes(snapshot)))


def _handle_node_current(state: ShellState) -> ShellResponse:
    """Render the current or latest shell workflow node."""
    snapshot = _latest_snapshot(state)
    if snapshot is None:
        return ShellResponse("No node yet. Type a natural-language goal first.")
    rendered = render_node_view(current_node(snapshot))
    if snapshot.pause_records:
        pause = snapshot.pause_records[-1]
        rendered = "\n".join(
            [
                rendered,
                "Paused:",
                f"- Reason: {pause.reason}",
                f"- Question: {pause.question}",
                f"- Requested input: {pause.requested_input}",
                "- Continue with: /resume <message>",
            ]
        )
    return ShellResponse(rendered)


def _latest_snapshot(state: ShellState) -> WorkflowSnapshot | None:
    """Load the latest workflow snapshot from SQLite or shell cache."""
    if _database_exists(state):
        connection = _connect_state(state)
        try:
            try:
                state.latest_snapshot = load_latest_workflow_snapshot(connection)
            except ValueError:
                return state.latest_snapshot
        finally:
            connection.close()
    return state.latest_snapshot


def _handle_goal_current(state: ShellState) -> ShellResponse:
    """Render the latest draft or accepted goal."""
    if _database_exists(state):
        connection = _connect_state(state)
        try:
            goal_run = load_latest_goal_run(connection)
            discovery = load_latest_discovery_session(connection, str(state.project_root))
            latest_draft = (
                load_goal_draft_for_discovery(connection, discovery.id)
                if discovery is not None
                else None
            )
            if (
                latest_draft is not None
                and goal_run is not None
                and latest_draft.updated_at > goal_run.started_at
            ):
                return ShellResponse(
                    f"Draft goal:\n{latest_draft.contract.get('summary', '')}"
                )
            if goal_run is not None:
                revision = load_goal_revision(connection, goal_run.goal_revision_id)
                if revision is not None:
                    return ShellResponse(
                        "\n".join(
                            [
                                "Accepted goal:",
                                str(revision.contract.get("summary", "")),
                                f"Revision: {revision.id}",
                                f"Run: {goal_run.loop_run_id}",
                            ]
                        )
                    )

            if latest_draft is not None:
                return ShellResponse(f"Draft goal:\n{latest_draft.contract.get('summary', '')}")
        finally:
            connection.close()

    if state.pending_goal is not None:
        return ShellResponse(f"Draft goal:\n{state.pending_goal.summary}")
    return ShellResponse("No current goal. Type a natural-language request first.")


def _history_text(state: ShellState) -> str:
    """Render durable discovery and runtime history."""
    lines = ["History:"]
    if not _database_exists(state):
        return "History:\n- none"

    connection = _connect_state(state)
    try:
        discovery = load_latest_discovery_session(connection, str(state.project_root))
        if discovery is not None:
            lines.append("Discovery discussion:")
            for turn in load_discussion_turns(connection, discovery.id):
                lines.append(f"- {turn.role}: {turn.content}")
        goal_run = load_latest_goal_run(connection)
        if goal_run is not None:
            lines.extend(
                [
                    "Goal runs:",
                    f"- {goal_run.goal_revision_id} -> {goal_run.loop_run_id} ({goal_run.status.value})",
                ]
            )
        pause = load_latest_pause_record(connection)
        if pause is not None:
            lines.extend(["Pause/resume:", f"- paused: {pause.reason}"])
    finally:
        connection.close()

    if len(lines) == 1:
        lines.append("- none")
    return "\n".join(lines)


def _handle_history(state: ShellState) -> ShellResponse:
    """Render durable shell history."""
    return ShellResponse(_history_text(state))


def _handle_goal_history(state: ShellState) -> ShellResponse:
    """Render durable goal history."""
    return _handle_history(state)


def _record_goal_approval(
    state: ShellState, goal: GoalContract, message: str = "accepted from shell yes"
) -> None:
    """Persist explicit user approval for accepting one goal."""
    now = _now()
    connection = _connect_state(state)
    try:
        approval = ApprovalRequestRecord(
            id=f"approval-goal-{goal.id}",
            session_id=f"session-router-{goal.id}",
            kind=ApprovalKind.GOAL,
            title="Approve goal",
            description=goal.summary,
            status=ApprovalStatus.APPROVED,
            requested_by="pm.goal-owner.1",
            scope={"goal_id": goal.id},
            created_at=now,
            updated_at=now,
        )
        insert_approval_request(connection, approval)
        insert_approval_decision(
            connection,
            ApprovalDecisionRecord(
                id=f"decision-{approval.id}",
                approval_request_id=approval.id,
                decision=ApprovalStatus.APPROVED,
                decided_by="user",
                message=message,
                created_at=now,
            ),
        )
    finally:
        connection.close()


def _handle_approval_decision(
    state: ShellState, text: str, status: ApprovalStatus
) -> ShellResponse:
    """Apply one approval mutation while holding the project write lock."""
    with project_write_lock(state.project_root):
        return _handle_approval_decision_unlocked(state, text, status)


def _handle_approval_decision_unlocked(
    state: ShellState, text: str, status: ApprovalStatus
) -> ShellResponse:
    """Apply a user decision to one pending approval request."""
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        return ShellResponse(f"Usage: /{status.value} <approval-id> [message]")
    approval_id = parts[1]
    message = parts[2] if len(parts) > 2 else status.value
    if not _database_exists(state):
        return ShellResponse(f"No approval request found: {approval_id}")

    now = _now()
    connection = _connect_state(state)
    try:
        approvals = {approval.id: approval for approval in load_approval_requests(connection)}
        approval = approvals.get(approval_id)
        if approval is None:
            return ShellResponse(f"No approval request found: {approval_id}")
        updated = approval.model_copy(update={"status": status, "updated_at": now})
        insert_approval_request(connection, updated)
        insert_approval_decision(
            connection,
            ApprovalDecisionRecord(
                id=f"decision-{approval_id}-{status.value}",
                approval_request_id=approval_id,
                decision=status,
                decided_by="user",
                message=message,
                created_at=now,
            ),
        )
    finally:
        connection.close()
    return ShellResponse(f"{status.value} {approval_id}: {message}")


def _uninitialized_notice(view: str) -> ShellResponse:
    """Return the guidance shown when no Curator state exists yet."""
    return ShellResponse(
        f"{view}: Curator is not initialized here.\nNext: /init (or curator init)"
    )


def _handle_workbench(state: ShellState) -> ShellResponse:
    """Render the durable Runtime Workspace view."""
    if not _database_exists(state):
        return _uninitialized_notice("Agent Runtime Workspace")
    connection = _connect_state(state)
    try:
        mode = resolve_mode_for_project(state.project_root)
        header = f"Agent Runtime Workspace\nMode: {mode.label} — {mode.detail}"
        return ShellResponse(render_workbench(connection).replace(
            "Agent Runtime Workspace", header, 1
        ))
    finally:
        connection.close()


def _handle_agents(state: ShellState) -> ShellResponse:
    """Render durable role pool state."""
    if not _database_exists(state):
        return _uninitialized_notice("Agents")
    connection = _connect_state(state)
    try:
        return ShellResponse(render_agents(connection))
    finally:
        connection.close()


def _handle_providers(state: ShellState) -> ShellResponse:
    """Render durable provider profile state."""
    if not _database_exists(state):
        return _uninitialized_notice("Providers")
    connection = _connect_state(state)
    try:
        return ShellResponse(render_providers(connection))
    finally:
        connection.close()


def _handle_provider_add(state: ShellState, text: str) -> ShellResponse:
    """Detect and persist one real provider profile from the shell."""
    parts = text.split()
    if len(parts) != 3:
        return ShellResponse("Usage: /provider add <claude-code|codex>")
    if not _database_exists(state):
        return ShellResponse(
            "Curator is not initialized here.\n"
            "Run /setup for guided setup, or /init to create state first."
        )
    connection = _connect_state(state)
    try:
        result = add_provider_profile(connection, parts[2])
    finally:
        connection.close()
    if result.profile is None:
        return ShellResponse(result.message)
    return ShellResponse(
        "\n".join(
            [
                result.message,
                f"Next: /agent bind writer.default {result.profile.id}",
            ]
        )
    )


def _handle_agent_status(state: ShellState, text: str) -> ShellResponse:
    """Render provider choices for one role instance."""
    parts = text.split()
    if len(parts) != 3:
        return ShellResponse("Usage: /agent status <agent>")

    if not _database_exists(state):
        return ShellResponse(f"Unknown agent: {parts[2]}")
    connection = _connect_state(state)
    try:
        return ShellResponse(render_agent_status(connection, parts[2]))
    finally:
        connection.close()


def _role_instance_exists(connection, role_instance_id: str) -> bool:
    """Return whether a role instance exists in durable state."""
    return any(role.id == role_instance_id for role in load_role_instances(connection))


def _handle_agent_provider_binding(
    state: ShellState, text: str, verb: str
) -> ShellResponse:
    """Bind or switch one role instance to a provider profile."""
    parts = text.split()
    if len(parts) != 4:
        return ShellResponse(f"Usage: /agent {verb} <agent> <profile>")

    role_instance_id = parts[2]
    provider_profile_id = parts[3]
    now = _now()
    connection = _connect_state(state)
    try:
        if not _role_instance_exists(connection, role_instance_id):
            return ShellResponse(f"Unknown agent: {role_instance_id}")
        profile = load_provider_profile(connection, provider_profile_id)
        if profile is None:
            return ShellResponse(f"Unknown provider profile: {provider_profile_id}")
        active = load_provider_binding_for_role(connection, role_instance_id)
        if active is not None and active.provider_profile_id == provider_profile_id:
            return ShellResponse(
                f"Agent {role_instance_id} already bound to {provider_profile_id}"
            )
        insert_role_provider_binding(
            connection,
            RoleProviderBindingRecord(
                id=f"binding-{role_instance_id}-{provider_profile_id}",
                role_instance_id=role_instance_id,
                provider_profile_id=provider_profile_id,
                status=ProviderBindingStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
    finally:
        connection.close()

    action = "Bound" if verb == "bind" else "Switched"
    return ShellResponse(f"{action} {role_instance_id} to {provider_profile_id}")


def _handle_queue(state: ShellState) -> ShellResponse:
    """Render durable work queue state."""
    if not _database_exists(state):
        return _uninitialized_notice("Queue")
    connection = _connect_state(state)
    try:
        return ShellResponse(render_queue(connection))
    finally:
        connection.close()


def _handle_queue_tick(state: ShellState) -> ShellResponse:
    """Assign pending durable work to idle role instances."""
    with project_write_lock(state.project_root):
        return _handle_queue_tick_unlocked(state)


def _handle_queue_tick_unlocked(state: ShellState) -> ShellResponse:
    """Assign pending durable work while holding the project write lock."""
    connection = _connect_state(state)
    try:
        decisions = tick_work_queue(connection)
    finally:
        connection.close()
    if not decisions:
        return ShellResponse("Queue tick: no pending work.")
    return ShellResponse("\n".join(["Queue tick:", *[f"- {decision}" for decision in decisions]]))


def _handle_approvals(state: ShellState) -> ShellResponse:
    """Render durable approval request state."""
    if not _database_exists(state):
        return _uninitialized_notice("Approvals")
    connection = _connect_state(state)
    try:
        return ShellResponse(render_approvals(connection))
    finally:
        connection.close()


def _handle_session_current(state: ShellState) -> ShellResponse:
    """Render the latest durable session state."""
    if not _database_exists(state):
        return ShellResponse("No current session.")
    connection = _connect_state(state)
    try:
        session = load_latest_session(connection)
    finally:
        connection.close()
    if session is None:
        return ShellResponse("No current session.")
    status = session.status.value if hasattr(session.status, "value") else session.status
    return ShellResponse(
        "\n".join(
            [
                "Current session:",
                f"- Id: {session.id}",
                f"- Mode: {session.mode.value}",
                f"- Status: {status}",
                f"- Project: {session.project_root}",
            ]
        )
    )


def _handle_sessions(state: ShellState) -> ShellResponse:
    """Render all durable sessions and their latest loop statuses."""
    if not _database_exists(state):
        return ShellResponse("Sessions:\n- none")
    connection = _connect_state(state)
    try:
        sessions = load_sessions_for_project(connection, str(state.project_root))
        lines = ["Sessions:"]
        for session in sessions:
            runs = load_loop_runs_for_session(connection, session.id)
            latest = runs[-1] if runs else None
            status = latest.status.value if latest is not None else session.status
            run_id = latest.id if latest is not None else "-"
            lines.append(f"- {session.id} [{status}] run={run_id}")
        return ShellResponse("\n".join(lines) if sessions else "Sessions:\n- none")
    finally:
        connection.close()


def _handle_memory(state: ShellState) -> ShellResponse:
    """Render distilled runtime memory lessons."""
    if not _database_exists(state):
        return ShellResponse(
            "Memory:\n- none yet — Curator records lessons when loops fail or pause."
        )
    connection = _connect_state(state)
    try:
        return ShellResponse(render_memory(connection))
    finally:
        connection.close()


def _existing_goal_ids(state: ShellState) -> set[str]:
    """Return goal ids already used by drafts or the ledger."""
    ids: set[str] = set()
    drafts_dir = build_curator_paths(state.project_root).goals_dir / "drafts"
    if drafts_dir.exists():
        ids.update(path.stem for path in drafts_dir.glob("*.yaml"))
    if _database_exists(state):
        connection = _connect_state(state)
        try:
            ids.update(load_goal_ids(connection))
        finally:
            connection.close()
    return ids


def _handle_evidence(state: ShellState) -> ShellResponse:
    """Render evidence refs for the latest goal run."""
    if not _database_exists(state):
        return ShellResponse("Evidence:\n- none")
    connection = _connect_state(state)
    try:
        goal_run = load_latest_goal_run(connection)
        if goal_run is None:
            return ShellResponse("Evidence:\n- none")
        evidence_refs = load_evidence_refs_for_run(connection, goal_run.loop_run_id)
    finally:
        connection.close()
    if not evidence_refs:
        return ShellResponse("Evidence:\n- none")
    lines = ["Evidence:"]
    lines.extend(
        f"- {evidence.id} [{evidence.kind.value}] {evidence.summary}"
        for evidence in evidence_refs
    )
    return ShellResponse("\n".join(lines))


def _handle_slash_command(state: ShellState, text: str) -> ShellResponse:
    """Route one slash command to a shell action."""
    if text == "/quit":
        state.should_exit = True
        return ShellResponse("Bye.", should_exit=True)
    if text == "/init":
        return ShellResponse(apply_first_run_init(state.project_root))
    if text == "/setup":
        return ShellResponse(run_setup_wizard(state.project_root).message)
    if text == "/help":
        return ShellResponse(_help_text())
    if text == "/help all":
        return ShellResponse(_help_text(full=True))
    if text == "/status":
        return _handle_status(state)
    if text == "/doctor":
        return _handle_doctor(state)
    if text == "/validate":
        return _handle_validate(state)
    if text == "/node list":
        return _handle_node_list(state)
    if text == "/node current":
        return _handle_node_current(state)
    if text == "/goal current":
        return _handle_goal_current(state)
    if text == "/goal start":
        return _handle_accept_goal(state)
    if text == "/goal history":
        return _handle_goal_history(state)
    if text == "/history":
        return _handle_history(state)
    if text == "/session current":
        return _handle_session_current(state)
    if text == "/sessions":
        return _handle_sessions(state)
    if text == "/workbench":
        return _handle_workbench(state)
    if text == "/agents":
        return _handle_agents(state)
    if text == "/providers":
        return _handle_providers(state)
    if text.startswith("/provider add"):
        return _handle_provider_add(state, text)
    if text == "/agent status" or text.startswith("/agent status "):
        return _handle_agent_status(state, text)
    if text.startswith("/agent bind "):
        return _handle_agent_provider_binding(state, text, "bind")
    if text.startswith("/agent switch "):
        return _handle_agent_provider_binding(state, text, "switch")
    if text == "/queue":
        return _handle_queue(state)
    if text == "/queue tick":
        return _handle_queue_tick(state)
    if text == "/approvals":
        return _handle_approvals(state)
    if text == "/evidence":
        return _handle_evidence(state)
    if text == "/memory":
        return _handle_memory(state)
    if text.startswith("/approve "):
        return _handle_approval_decision(state, text, ApprovalStatus.APPROVED)
    if text.startswith("/reject "):
        return _handle_approval_decision(state, text, ApprovalStatus.REJECTED)
    if text.startswith("/resume"):
        return _handle_resume(state, text.removeprefix("/resume").strip())
    if text.startswith("/revise"):
        return _handle_revise(state, text.removeprefix("/revise").strip())
    if text == "/gate" or text.startswith("/gate "):
        return _handle_gate(state, text)
    if text == "/cancel":
        return _handle_cancel_goal(state)
    return ShellResponse(_unknown_command_text(text))


KNOWN_SLASH_ROOTS = (
    "/help", "/quit", "/init", "/setup", "/status", "/doctor", "/validate", "/node", "/goal",
    "/history", "/session", "/sessions", "/workbench", "/agents", "/providers",
    "/provider", "/agent", "/queue", "/approvals", "/approve", "/reject",
    "/evidence", "/memory", "/resume", "/revise", "/gate", "/cancel",
)

# Full command phrases used for interactive completion suggestions.
KNOWN_SLASH_COMMANDS = (
    "/help", "/help all", "/setup", "/init", "/status", "/doctor", "/validate",
    "/goal current", "/goal start", "/goal history", "/node list", "/node current",
    "/resume", "/revise", "/gate on", "/gate off", "/cancel", "/history",
    "/session current", "/sessions", "/workbench", "/agents", "/providers",
    "/provider add claude-code", "/provider add codex", "/agent status",
    "/agent bind", "/agent switch", "/queue", "/queue tick", "/approvals",
    "/approve", "/reject", "/evidence", "/memory", "/quit",
)

_SLASH_DESCRIPTIONS = {
    "/help": "Show task-oriented help",
    "/help all": "Show every shell command",
    "/setup": "Configure PM, Engineer, Reviewer, and providers",
    "/init": "Create Curator state in this project",
    "/status": "Show current project status",
    "/doctor": "Run diagnostics and environment checks",
    "/goal current": "Show the current goal draft",
    "/goal start": "Start the saved goal draft",
    "/goal history": "Show goal and discovery history",
    "/gate on": "Require proposal approval",
    "/gate off": "Start small requests immediately",
    "/provider add claude-code": "Connect Claude Code",
    "/provider add codex": "Connect Codex",
    "/quit": "Exit the Curator shell",
}

SLASH_COMMAND_SPECS: tuple[tuple[str, str], ...] = tuple(
    (command, _SLASH_DESCRIPTIONS.get(command, "Run this Curator command"))
    for command in KNOWN_SLASH_COMMANDS
)


def _unknown_command_text(text: str) -> str:
    """Return the unknown-command notice with a closest-match suggestion."""
    from difflib import get_close_matches

    first = text.split()[0]
    matches = get_close_matches(first, KNOWN_SLASH_ROOTS, n=1, cutoff=0.6)
    if not matches:
        return f"Unknown command: {text}\nType /help for commands."
    return f"Unknown command: {text}\nDid you mean {matches[0]}? (/help for all commands)"


def _handle_gate(state: ShellState, text: str) -> ShellResponse:
    """Show or toggle proposal gate mode."""
    parts = text.split()
    if len(parts) == 1:
        return ShellResponse(f"Gate mode: {'on' if state.gate_mode else 'off'}")
    if parts[1] == "on":
        state.gate_mode = True
        return ShellResponse("Gate mode on: proposals require yes/no/edit before running.")
    if parts[1] == "off":
        state.gate_mode = False
        return ShellResponse("Gate mode off: small requests start immediately.")
    return ShellResponse("Usage: /gate [on|off]")


def _print_progress_event(event: ProviderEvent) -> None:
    """Print one live progress line for a streaming provider event."""
    if event.kind is ProviderEventKind.OUTPUT_CHUNK:
        return
    label = f" {event.label}" if event.label else ""
    print(f"  [{event.kind.value}]{label}", flush=True)


def _resolve_scope_change_pause(state: ShellState, goal: GoalContract) -> None:
    """Resolve the pause a revised goal was drafted from, when still open."""
    pause_id = goal.metadata.get("scope_change_from_pause_id")
    if not pause_id or not _database_exists(state):
        return

    connection = _connect_state(state)
    try:
        pause = load_latest_pause_record(connection)
        if pause is None or pause.id != pause_id:
            return
        now = _now()
        insert_resume_event(
            connection,
            ResumeEventRecord(
                id=f"resume-{pause.id}-revise",
                pause_id=pause.id,
                loop_run_id=pause.loop_run_id,
                session_id=pause.session_id,
                message=f"superseded by revised goal {goal.id}",
                action="revise",
                created_at=now,
            ),
        )
        insert_pause_record(
            connection,
            pause.model_copy(update={"status": PauseStatus.RESOLVED, "resolved_at": now}),
        )
    finally:
        connection.close()


def _start_accepted_goal(state: ShellState, auto: bool = False) -> ShellResponse:
    """Accept the pending proposal and start its loop."""
    with project_write_lock(state.project_root):
        return _start_accepted_goal_unlocked(state, auto=auto)


def _start_accepted_goal_unlocked(state: ShellState, auto: bool = False) -> ShellResponse:
    """Accept one proposal while the caller owns the project write lock."""
    if state.pending_goal is None:
        state.pending_goal = _latest_durable_goal_draft(state)
    if state.pending_goal is None:
        return ShellResponse("No pending goal. Type what you want to work on first.")

    paths = build_curator_paths(state.project_root)
    _record_goal_approval(
        state,
        state.pending_goal,
        message="auto-accepted (fast path)" if auto else "accepted from shell yes",
    )
    save_goal(paths, state.pending_goal)
    _resolve_scope_change_pause(state, state.pending_goal)
    acceptance = accept_goal(paths, state.pending_goal.id)
    try:
        snapshot = start_goal_loop(
            state.project_root,
            acceptance.revision_id,
            on_event=state.emit_event or _print_progress_event,
            cancellation=state.cancellation,
        )
    except (KeyboardInterrupt, ProjectLockedError) as error:
        state.pending_goal = None
        if isinstance(error, ProjectLockedError):
            return ShellResponse(str(error))
        return ShellResponse(
            "Run interrupted. Ledger state is preserved — /workbench to inspect."
        )
    state.latest_snapshot = snapshot
    state.pending_goal = None
    if auto:
        header = (
            f"Starting now: {acceptance.goal.summary}\n"
            f"(goal {acceptance.goal.id} accepted — /gate on to review proposals first)"
        )
    else:
        header = f"Goal accepted: {acceptance.goal.id}"
    lines = [header, *render_workflow_lines(snapshot)]
    return ShellResponse("\n".join(lines))


def _handle_accept_goal(state: ShellState) -> ShellResponse:
    """Accept the pending proposal and start its loop."""
    return _start_accepted_goal(state)


def _handle_cancel_goal(state: ShellState) -> ShellResponse:
    """Discard the pending proposal without starting a loop."""
    with project_write_lock(state.project_root):
        return _handle_cancel_goal_unlocked(state)


def _handle_cancel_goal_unlocked(state: ShellState) -> ShellResponse:
    """Cancel a proposal or pause while holding the project write lock."""
    if _database_exists(state):
        connection = _connect_state(state)
        try:
            pause = load_latest_pause_record(connection)
            if pause is not None:
                now = _now()
                insert_resume_event(
                    connection,
                    ResumeEventRecord(
                        id=f"resume-{pause.id}-cancel",
                        pause_id=pause.id,
                        loop_run_id=pause.loop_run_id,
                        session_id=pause.session_id,
                        message="cancelled by user",
                        action="cancel",
                        created_at=now,
                    ),
                )
                insert_pause_record(
                    connection,
                    pause.model_copy(
                        update={"status": PauseStatus.RESOLVED, "resolved_at": now}
                    ),
                )
                state.pending_goal = None
                return ShellResponse("Paused loop cancelled.")
        finally:
            connection.close()
    state.pending_goal = None
    return ShellResponse("Goal proposal cancelled.")


def _latest_durable_goal_draft(state: ShellState) -> GoalContract | None:
    """Load the latest durable goal draft from SQLite."""
    if not _database_exists(state):
        return None
    connection = _connect_state(state)
    try:
        discovery = load_latest_discovery_session(connection, str(state.project_root))
        if discovery is None:
            return None
        draft = load_goal_draft_for_discovery(connection, discovery.id)
        if draft is None:
            return None
        return GoalContract.model_validate(draft.contract)
    finally:
        connection.close()


def _record_discovery_turn(
    state: ShellState,
    goal: GoalContract,
    text: str,
    metadata: dict | None = None,
) -> None:
    """Persist one PM discovery discussion turn and durable draft."""
    now = _now()
    connection = _connect_state(state)
    try:
        ensure_default_role_pool(connection)
        discovery = DiscoverySessionRecord(
            id=f"discovery-{goal.id}",
            project_root=str(state.project_root),
            status=DiscoveryStatus.ACTIVE,
            goal_id=goal.id,
            created_at=goal.created_at or now,
            updated_at=now,
            metadata=metadata or {},
        )
        insert_discovery_session(connection, discovery)
        insert_discussion_turn(
            connection,
            DiscussionTurnRecord(
                id=f"{discovery.id}-turn-{now.timestamp():.0f}",
                discovery_session_id=discovery.id,
                role="user",
                content=text,
                created_at=now,
                metadata=metadata or {},
            ),
        )
        insert_goal_draft(
            connection,
            GoalDraftRecord(
                id=f"draft-{goal.id}",
                discovery_session_id=discovery.id,
                goal_id=goal.id,
                status=DiscoveryStatus.ACTIVE,
                contract=goal.model_dump(mode="json"),
                created_at=goal.created_at or now,
                updated_at=now,
                metadata=metadata or {},
            ),
        )
    finally:
        connection.close()


def _handle_scope_change(state: ShellState, text: str, pause_id: str) -> ShellResponse:
    """Create a durable revised goal draft from a paused scope change."""
    paths = build_curator_paths(state.project_root)
    goal = propose_goal(text, existing_ids=_existing_goal_ids(state)).model_copy(
        update={"metadata": {"scope_change_from_pause_id": pause_id}}
    )
    save_goal(paths, goal)
    _record_discovery_turn(
        state,
        goal,
        text,
        metadata={"scope_change_from_pause_id": pause_id},
    )
    state.pending_goal = goal
    return ShellResponse(_render_goal_proposal(goal, revised=True))


def _handle_resume(state: ShellState, message: str) -> ShellResponse:
    """Answer the latest pause, resolve it, and resume when supported."""
    cleaned = message.strip()
    loop_run_id: str | None = None
    parts = cleaned.split(maxsplit=2)
    if len(parts) >= 2 and parts[0] == "--run":
        loop_run_id = parts[1]
        cleaned = parts[2].strip() if len(parts) == 3 else ""
    if not cleaned:
        return ShellResponse("Resume needs a message: /resume <message>")
    if not _database_exists(state):
        return ShellResponse("No paused loop to resume.")

    connection = _connect_state(state)
    try:
        pause = load_latest_pause_record(connection, loop_run_id)
        if pause is None:
            return ShellResponse("No paused loop to resume.")
        # Record the resume as a durable audit event, but let resume_workflow
        # own resolving the pause so the executable resume path can find it.
        insert_resume_event(
            connection,
            ResumeEventRecord(
                id=f"resume-{pause.id}-{len(cleaned)}",
                pause_id=pause.id,
                loop_run_id=pause.loop_run_id,
                session_id=pause.session_id,
                message=cleaned,
                action="continue_current_node",
                created_at=_now(),
            ),
        )
    finally:
        connection.close()

    snapshot = resume_goal_loop(
        state.project_root,
        cleaned,
        on_event=state.emit_event or _print_progress_event,
        cancellation=state.cancellation,
        loop_run_id=loop_run_id,
    )
    if snapshot is None:
        return ShellResponse(f"Resume recorded: {cleaned}")
    state.latest_snapshot = snapshot
    return ShellResponse("\n".join(["Resumed.", *render_workflow_lines(snapshot)]))


def _handle_revise(state: ShellState, message: str) -> ShellResponse:
    """Draft a revised goal proposal from the latest pause."""
    cleaned = message.strip()
    if not cleaned:
        return ShellResponse("Revise needs a message: /revise <new scope>")
    if not _database_exists(state):
        return ShellResponse("No paused loop to revise.")

    connection = _connect_state(state)
    try:
        pause = load_latest_pause_record(connection)
    finally:
        connection.close()
    if pause is None:
        return ShellResponse("No paused loop to revise.")
    return _handle_scope_change(state, cleaned, pause.id)


def _paused_input_notice(state: ShellState) -> ShellResponse:
    """Explain the explicit choices while a loop is paused."""
    connection = _connect_state(state)
    try:
        pause = load_latest_pause_record(connection)
    finally:
        connection.close()
    question = pause.question if pause is not None else ""
    return ShellResponse(
        "\n".join(
            [
                f"A loop is paused: {question}",
                "- /resume <your answer>   answer and continue",
                "- /revise <new scope>     change the goal",
                "- /cancel                 stop this loop",
            ]
        )
    )


def _paused_loop_exists(state: ShellState) -> bool:
    """Return whether an open pause exists in durable state."""
    if not _database_exists(state):
        return False

    connection = _connect_state(state)
    try:
        return load_latest_pause_record(connection) is not None
    finally:
        connection.close()


def _setup_mode_refusal(state: ShellState, mode) -> ShellResponse:
    """Refuse to start work in setup mode without touching any state."""
    lines = [
        f"Curator is in setup mode ({mode.detail}) — nothing was started or saved.",
        "- /setup — guided setup (roles → providers → login)",
        "Or set up manually:",
    ]
    if first_run_needed(state.project_root):
        lines.append("- /init — create Curator state here")
    lines.extend(
        [
            "- /provider add claude-code   (or: /provider add codex)",
            "- /agent bind writer.default claude-code",
            "Then type your request again.",
        ]
    )
    return ShellResponse("\n".join(lines))


def _handle_natural_language(state: ShellState, text: str) -> ShellResponse:
    """Create a goal proposal, gating only large or opted-in requests."""
    mode = resolve_mode_for_project(state.project_root)
    if mode.label == "setup":
        return _setup_mode_refusal(state, mode)
    paths = build_curator_paths(state.project_root)
    goal = propose_goal(text, existing_ids=_existing_goal_ids(state))
    save_goal(paths, goal)
    if _should_gate(state, text):
        _record_discovery_turn(state, goal, text)
        state.pending_goal = goal
        return ShellResponse(_render_goal_proposal(goal), menu=proposal_menu())

    _record_discovery_turn(state, goal, text, metadata={"fast_path": True})
    state.pending_goal = goal
    return _start_accepted_goal(state, auto=True)


def _handle_proposal_answer(state: ShellState, stripped: str, lowered: str) -> ShellResponse:
    """Handle yes/no/edit answers for the pending proposal."""
    if lowered in {"yes", "y", "start"}:
        return _handle_accept_goal(state)
    if lowered in {"no", "n", "cancel"}:
        return _handle_cancel_goal(state)
    state.pending_goal = _apply_goal_edit(state.pending_goal, stripped[5:])
    save_goal(build_curator_paths(state.project_root), state.pending_goal)
    return ShellResponse(_render_goal_proposal(state.pending_goal), menu=proposal_menu())


def _handle_shell_input(state: ShellState, text: str) -> ShellResponse:
    """Handle one line of shell input inside the guarded dispatch boundary."""
    stripped = text.strip()
    lowered = stripped.lower()
    if not stripped:
        return ShellResponse("")
    if stripped.startswith("/"):
        try:
            return _handle_slash_command(state, stripped)
        except ProjectLockedError as error:
            return ShellResponse(str(error))
    is_answer = lowered in {"yes", "y", "start", "no", "n", "cancel"} or lowered.startswith(
        "edit "
    )
    if state.pending_goal is not None and is_answer:
        return _handle_proposal_answer(state, stripped, lowered)
    command_intent = detect_cli_command(stripped)
    if command_intent is not None:
        return ShellResponse(render_command_hint(command_intent))
    if _paused_loop_exists(state):
        return _paused_input_notice(state)
    if is_answer:
        lines = ["No pending proposal to answer."]
        if _latest_durable_goal_draft(state) is not None:
            lines.append(
                "A saved draft exists — review it with /goal current, start it with /goal start."
            )
        lines.append("Type what you want to work on, or /help.")
        return ShellResponse("\n".join(lines))
    return _handle_natural_language(state, stripped)


def handle_shell_input(state: ShellState, text: str) -> ShellResponse:
    """Handle one line and convert unexpected failures into logged responses."""
    try:
        return _handle_shell_input(state, text)
    except ProjectLockedError as error:
        return ShellResponse(str(error))
    except Exception as error:
        return ShellResponse(
            recoverable_error_message(state.project_root, "shell input", error)
        )


def _offer_first_run_init(project_root: Path) -> None:
    """Offer the setup wizard for a fresh project on an interactive terminal."""
    import sys

    if not first_run_needed(project_root) or not sys.stdin.isatty():
        return
    print("This project is not initialized yet.")
    try:
        answer = input("Run the setup wizard now? [Y/n] ")
    except EOFError:
        return
    if answer.strip().lower() in {"", "y", "yes"}:
        print(run_setup_wizard(project_root).message)


def _should_run_preflight() -> bool:
    """Return whether startup preflight probes should run.

    Interactive terminals always get the preflight; pipes and tests skip
    the subprocess probes unless CURATOR_PREFLIGHT=force is set.
    """
    import os
    import sys

    if os.environ.get("CURATOR_PREFLIGHT") == "force":
        return True
    if os.environ.get("CURATOR_PREFLIGHT") == "skip":
        return False
    return sys.stdin.isatty()


def run_interactive_shell(project_root: Path, gate: bool = True) -> None:
    """Run the blocking stdin/stdout Curator shell."""
    from curator.tui.prompt_input import (
        configure_shell_completion,
        load_shell_history,
        read_multiline,
        save_shell_history,
    )

    import sys

    state = ShellState(project_root=project_root, gate_mode=gate)
    print(render_banner(project_root))
    print()
    try:
        recovered = reconcile_project(project_root)
    except Exception as error:
        print(recoverable_error_message(project_root, "startup recovery", error))
        recovered = 0
    if recovered:
        print(f"Recovered {recovered} interrupted run(s).")
    if _should_run_preflight():
        try:
            print(render_preflight(run_preflight(project_root)))
        except Exception as error:
            print(recoverable_error_message(project_root, "startup preflight", error))
        print()
    _offer_first_run_init(project_root)
    print(build_welcome_text(project_root))
    history_enabled = sys.stdin.isatty()
    try:
        if history_enabled:
            try:
                load_shell_history(project_root)
                configure_shell_completion()
            except Exception as error:
                print(recoverable_error_message(project_root, "shell history", error))
        while not state.should_exit:
            try:
                line = read_multiline(_prompt_prefix(state))
            except EOFError:
                break
            response = handle_shell_input(state, line)
            if response.text:
                print(response.text)
            if response.should_exit:
                break
    finally:
        if history_enabled:
            try:
                save_shell_history(project_root)
            except Exception as error:
                print(recoverable_error_message(project_root, "shell history", error))

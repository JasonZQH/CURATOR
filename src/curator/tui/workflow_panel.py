"""Render workflow state as a terminal-first status panel."""

from curator.core.schema import TaskRecord, WorkflowSnapshot


def _task_role_id(task: TaskRecord) -> str:
    """Return the display role id for a task."""
    return str(task.metadata.get("role_id", task.role.value))


def _task_line(task: TaskRecord) -> str:
    """Return one terminal line for a workflow task."""
    role_id = _task_role_id(task)
    suffix = "" if role_id == task.role.value else f" [{role_id}]"
    return f"- {task.role.value}: {task.status.value} - {task.title}{suffix}"


def _selection_lines(snapshot: WorkflowSnapshot) -> list[str]:
    """Return terminal lines that explain dynamic role selections."""
    if not snapshot.role_selections:
        return []

    lines = ["Selected Roles:"]
    for selection in snapshot.role_selections:
        signals = ", ".join(selection.matched_signals)
        lines.append(f"- {selection.display_name}: {signals} (score {selection.score})")
        lines.append(f"  {selection.reason}")

    return lines


def _last_decision_line(snapshot: WorkflowSnapshot) -> str | None:
    """Return the final decision line when the snapshot has decisions."""
    if not snapshot.loop_decisions:
        return None

    return f"Decision: {snapshot.loop_decisions[-1].decision.value}"


def _last_stop_line(snapshot: WorkflowSnapshot) -> str | None:
    """Return the final stop condition line when the snapshot has one."""
    if not snapshot.loop_decisions:
        return None

    stop_condition = snapshot.loop_decisions[-1].stop_condition
    if stop_condition is None:
        return None

    return f"Stop: {stop_condition.value}"


def render_workflow_lines(snapshot: WorkflowSnapshot) -> list[str]:
    """Render a workflow snapshot into terminal-friendly status lines."""
    loop_name = snapshot.loop_runs[-1].template_id if snapshot.loop_runs else "none"
    lines = [
        f"Session: {snapshot.session.id}",
        f"Loop: {loop_name}",
        "Tasks:",
        *[_task_line(task) for task in snapshot.tasks],
    ]
    lines.extend(_selection_lines(snapshot))

    decision_line = _last_decision_line(snapshot)
    if decision_line is not None:
        lines.append(decision_line)

    stop_line = _last_stop_line(snapshot)
    if stop_line is not None:
        lines.append(stop_line)

    lines.append(f"Evidence: {len(snapshot.evidence_refs)}")
    return lines


def render_runtime_panel(snapshot: WorkflowSnapshot) -> str:
    """Render the runtime summary panel for the TUI."""
    loop_run = snapshot.loop_runs[-1] if snapshot.loop_runs else None
    loop_id = loop_run.id if loop_run else "none"
    loop_status = loop_run.status.value if loop_run else snapshot.session.status
    return "\n".join(
        [
            "Runtime",
            f"Session: {snapshot.session.id}",
            f"Loop: {loop_id}",
            f"Status: {loop_status}",
        ]
    )


def render_agents_panel(snapshot: WorkflowSnapshot) -> str:
    """Render active role and task state for the TUI."""
    lines = ["Active Roles"]
    if not snapshot.tasks:
        return "Active Roles\n- none"
    for task in snapshot.tasks:
        lines.append(f"- {task.role.value}: {task.status.value} - {task.title}")
    return "\n".join(lines)


def render_providers_panel(snapshot: WorkflowSnapshot) -> str:
    """Render provider identities observed in the snapshot."""
    lines = ["Providers"]
    if not snapshot.provider_runs:
        return "Providers\n- none"
    seen = set()
    for run in snapshot.provider_runs:
        profile = run.provider_profile_id or run.provider.value
        key = (run.provider.value, profile)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {profile}: {run.provider.value}")
    return "\n".join(lines)


def render_evidence_panel(snapshot: WorkflowSnapshot) -> str:
    """Render evidence summaries observed in the snapshot."""
    lines = ["Evidence"]
    if not snapshot.evidence_refs:
        return "Evidence\n- none"
    for evidence in snapshot.evidence_refs[-6:]:
        lines.append(f"- {evidence.kind.value}: {evidence.summary}")
    return "\n".join(lines)


def render_events_panel(snapshot: WorkflowSnapshot) -> str:
    """Render provider and evidence events observed in the snapshot."""
    lines = ["Events"]
    for run in snapshot.provider_runs[-5:]:
        profile = run.provider_profile_id or run.provider.value
        lines.append(f"- provider {run.role.value} {run.status.value} via {profile}")
    for evidence in snapshot.evidence_refs[-5:]:
        lines.append(f"- evidence {evidence.kind.value} saved by {evidence.producer_role.value}")
    return "\n".join(lines) if len(lines) > 1 else "Events\n- none"

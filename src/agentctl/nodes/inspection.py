"""Build task-backed node views from workflow snapshots."""

from pydantic import Field

from agentctl.core.enums import RoleName, TaskStatus
from agentctl.core.models.base import CuratorModel
from agentctl.core.schema import (
    EvidenceRef,
    LoopDecisionRecord,
    LoopIterationRecord,
    TaskRecord,
    WorkflowSnapshot,
)


class NodeView(CuratorModel):
    """Describe a user-inspectable workflow node."""

    task_id: str
    role: RoleName
    status: TaskStatus
    task: str
    iteration: LoopIterationRecord | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    decision: LoopDecisionRecord | None = None
    warnings: list[str] = Field(default_factory=list)


def _latest_iteration_for_task(
    snapshot: WorkflowSnapshot, task: TaskRecord
) -> LoopIterationRecord | None:
    """Return the latest loop iteration attached to a task."""
    iterations = [
        iteration for iteration in snapshot.loop_iterations if iteration.task_id == task.id
    ]
    if not iterations:
        return None
    return iterations[-1]


def _latest_decision_for_iteration(
    snapshot: WorkflowSnapshot, iteration: LoopIterationRecord | None
) -> LoopDecisionRecord | None:
    """Return the latest decision attached to an iteration."""
    if iteration is None:
        return None
    decisions = [
        decision
        for decision in snapshot.loop_decisions
        if decision.iteration_id == iteration.id
    ]
    if not decisions:
        return None
    return decisions[-1]


def _evidence_for_iteration(
    snapshot: WorkflowSnapshot, iteration: LoopIterationRecord | None
) -> list[EvidenceRef]:
    """Return evidence refs produced by an iteration."""
    if iteration is None:
        return []
    return [
        evidence
        for evidence in snapshot.evidence_refs
        if evidence.iteration_id == iteration.id
    ]


def _node_for_task(snapshot: WorkflowSnapshot, task: TaskRecord) -> NodeView:
    """Build one node view for a task."""
    iteration = _latest_iteration_for_task(snapshot, task)
    return NodeView(
        task_id=task.id,
        role=task.role,
        status=task.status,
        task=task.title,
        iteration=iteration,
        evidence=_evidence_for_iteration(snapshot, iteration),
        decision=_latest_decision_for_iteration(snapshot, iteration),
    )


def list_nodes(snapshot: WorkflowSnapshot) -> list[NodeView]:
    """Return task-backed node views for a workflow snapshot."""
    return [_node_for_task(snapshot, task) for task in snapshot.tasks]


def current_node(snapshot: WorkflowSnapshot) -> NodeView | None:
    """Return the running node or latest completed node."""
    nodes = list_nodes(snapshot)
    if snapshot.pause_records:
        paused_task_id = snapshot.pause_records[-1].task_id
        paused_nodes = [node for node in nodes if node.task_id == paused_task_id]
        if paused_nodes:
            return paused_nodes[-1]
    running = [node for node in nodes if node.status is TaskStatus.RUNNING]
    if running:
        return running[-1]
    if nodes:
        return nodes[-1]
    return None


def render_node_list(nodes: list[NodeView]) -> str:
    """Render node summaries for shell display."""
    if not nodes:
        return "Nodes: none"

    lines = ["Nodes:"]
    for node in nodes:
        lines.append(
            f"- {node.task_id}: {node.role.value} / {node.status.value} / {node.task}"
        )
    return "\n".join(lines)


def render_node_view(node: NodeView | None) -> str:
    """Render one node view for shell display."""
    if node is None:
        return "No node yet. Type a natural-language goal or run /demo first."

    lines = [
        f"Node: {node.task_id}",
        f"Role: {node.role.value}",
        f"Status: {node.status.value}",
        f"Task: {node.task}",
        "Evidence:",
    ]
    if node.evidence:
        lines.extend(
            f"- {evidence.kind.value}: {evidence.summary}" for evidence in node.evidence
        )
    else:
        lines.append("- none")

    lines.append("Decision:")
    if node.decision is not None:
        lines.append(f"- {node.decision.decision.value}: {node.decision.reason}")
    else:
        lines.append("- none")

    lines.append("Warnings:")
    if node.warnings:
        lines.extend(f"- {warning}" for warning in node.warnings)
    else:
        lines.append("- none")
    return "\n".join(lines)

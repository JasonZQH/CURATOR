"""Verify task-backed node inspection views."""

from agentctl.app import run_workflow_snapshot
from agentctl.nodes.inspection import current_node, list_nodes, render_node_view
from fakes import CodingDeliveryFakeProvider


def test_node_inspection_returns_current_or_latest_node(tmp_path):
    """Verify node inspection can summarize the latest completed workflow task."""
    snapshot = run_workflow_snapshot(
        tmp_path,
        CodingDeliveryFakeProvider(),
        session_id="session-node-001",
    )

    nodes = list_nodes(snapshot)
    node = current_node(snapshot)
    rendered = render_node_view(node)

    assert [view.role.value for view in nodes] == ["pm", "engineer", "qa", "pm"]
    assert node is not None
    assert node.role.value == "pm"
    assert node.status.value == "done"
    assert "Node:" in rendered
    assert "Decision:" in rendered

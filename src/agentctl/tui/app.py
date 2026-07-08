"""Provide the Textual application shell for workflow display."""

from textual.app import App, ComposeResult
from textual.widgets import Static

from agentctl.core.schema import WorkflowSnapshot
from agentctl.tui.workflow_panel import (
    render_agents_panel,
    render_events_panel,
    render_evidence_panel,
    render_providers_panel,
    render_runtime_panel,
)


class WorkflowApp(App[None]):
    """Display a workflow snapshot as a Runtime Workspace."""

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, snapshot: WorkflowSnapshot) -> None:
        """Store the workflow snapshot rendered by the app."""
        super().__init__()
        self.snapshot = snapshot

    def compose(self) -> ComposeResult:
        """Compose the runtime-first workflow workspace."""
        yield Static(render_runtime_panel(self.snapshot), id="runtime-panel")
        yield Static(render_agents_panel(self.snapshot), id="agents-panel")
        yield Static(render_providers_panel(self.snapshot), id="providers-panel")
        yield Static(render_evidence_panel(self.snapshot), id="evidence-panel")
        yield Static(render_events_panel(self.snapshot), id="events-panel")

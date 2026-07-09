"""Verify the Textual Runtime Workspace app."""

import asyncio

from textual.widgets import Static

from curator.app import run_workflow_snapshot, write_init_state
from curator.tui.app import WorkflowApp
from fakes import CodingDeliveryFakeProvider


def test_workflow_app_renders_runtime_workspace_panels(tmp_path):
    """Verify the Textual app displays runtime-first workspace panels."""
    write_init_state(tmp_path)
    snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())

    async def run_app() -> None:
        """Run the Textual app headlessly and inspect workspace panels."""
        app = WorkflowApp(snapshot)
        async with app.run_test() as pilot:
            runtime = app.query_one("#runtime-panel", Static)
            agents = app.query_one("#agents-panel", Static)
            providers = app.query_one("#providers-panel", Static)
            evidence = app.query_one("#evidence-panel", Static)
            events = app.query_one("#events-panel", Static)

            assert "Runtime" in str(runtime.content)
            assert snapshot.session.id in str(runtime.content)
            assert "Active Roles" in str(agents.content)
            assert "engineer" in str(agents.content)
            assert "Providers" in str(providers.content)
            assert "codex" in str(providers.content)
            assert "Evidence" in str(evidence.content)
            assert "Events" in str(events.content)
            assert "provider engineer succeeded" in str(events.content)
            await pilot.press("q")

    asyncio.run(run_app())


def test_workflow_app_quit_binding_exits(tmp_path):
    """Verify the Textual app exposes a quit binding for the prototype."""
    write_init_state(tmp_path)
    snapshot = run_workflow_snapshot(tmp_path, CodingDeliveryFakeProvider())

    async def run_app() -> None:
        """Run the Textual app headlessly and quit with the keyboard binding."""
        app = WorkflowApp(snapshot)
        async with app.run_test() as pilot:
            await pilot.press("q")

    asyncio.run(run_app())

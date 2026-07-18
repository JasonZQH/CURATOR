"""Verify trust onboarding layout and retry behavior after an exit choice."""

import asyncio

from textual.widgets import OptionList

from curator.shell.trust import trust_decision
from curator.tui.shell_app import CuratorShellApp


def test_trust_screen_keeps_options_inside_the_dialog(tmp_path, monkeypatch):
    """Verify the trust choices render inside one centered modal card."""
    monkeypatch.setenv("CURATOR_TRUST", "force")
    monkeypatch.setenv("CURATOR_PREFLIGHT", "skip")
    monkeypatch.setenv("CURATOR_HOME", str(tmp_path / "curator-home"))

    async def run() -> None:
        app = CuratorShellApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen_stack[-1]
            options = screen.query_one("#trust-options", OptionList)
            assert options.parent is screen.query_one("#trust-content")
            assert options.option_count == 2

    asyncio.run(run())


def test_exiting_trust_allows_a_later_curator_launch(tmp_path, monkeypatch):
    """Verify Exit is session-scoped and does not persist a deny decision."""
    monkeypatch.setenv("CURATOR_TRUST", "force")
    monkeypatch.setenv("CURATOR_PREFLIGHT", "skip")
    monkeypatch.setenv("CURATOR_HOME", str(tmp_path / "curator-home"))

    async def run() -> None:
        first = CuratorShellApp(tmp_path)
        async with first.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")
            await pilot.pause()
            assert first.state.should_exit

        assert trust_decision(tmp_path) is None

        second = CuratorShellApp(tmp_path)
        async with second.run_test() as pilot:
            await pilot.pause()
            assert type(second.screen_stack[-1]).__name__ == "TrustScreen"

    asyncio.run(run())

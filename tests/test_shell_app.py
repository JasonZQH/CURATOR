"""Verify the full-screen Curator shell app."""

import asyncio

from textual.widgets import Input, Static

from curator.tui.shell_app import CuratorShellApp
from fakes import enable_live_mode


async def _submit_and_wait(app, pilot, text: str, expect: str) -> None:
    """Submit one input line and wait until the transcript contains text."""
    app.query_one("#input", Input).value = text
    await pilot.press("enter")
    for _ in range(100):
        await pilot.pause(0.05)
        if any(expect in block for block in app.transcript):
            return
    raise AssertionError(f"transcript never contained: {expect!r}")


def test_shell_app_starts_with_banner_and_setup_status(tmp_path):
    """Verify the app shows the banner and a setup-mode status bar."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.query_one("#status", Static).content)
            assert any("curator v0.1.0" in block for block in app.transcript)
            assert "setup" in status
            assert "gate:on" in status

    asyncio.run(run())


def test_shell_app_routes_slash_commands(tmp_path):
    """Verify submitted slash commands render through the shared contract."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await _submit_and_wait(app, pilot, "/help", "What do you want to do?")

    asyncio.run(run())


def test_shell_app_intercepts_terminal_command_input(tmp_path):
    """Verify the incident input gets the did-you-mean, not a goal."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await _submit_and_wait(
                app, pilot, "curator provider add claude-code", "not treated as a task"
            )
            assert not (tmp_path / ".curator").exists()

    asyncio.run(run())


def test_shell_app_status_bar_shows_live_bindings(tmp_path):
    """Verify a configured project reports live mode and seat bindings."""
    enable_live_mode(tmp_path)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.query_one("#status", Static).content)
            assert "live" in status
            assert "writer:claude-code" in status
            assert "reviewer:claude-code" in status

    asyncio.run(run())


def test_shell_app_suggests_slash_completions(tmp_path):
    """Verify typing a slash prefix surfaces matching commands."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#input", Input).value = "/pro"
            await pilot.pause()
            suggest = str(app.query_one("#suggest", Static).content)
            assert "/provider add claude-code" in suggest
            assert "/providers" in suggest

    asyncio.run(run())


def test_shell_app_quit_command_exits(tmp_path):
    """Verify /quit ends the app through the shared contract."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await _submit_and_wait(app, pilot, "/quit", "Bye.")
            assert app.state.should_exit

    asyncio.run(run())

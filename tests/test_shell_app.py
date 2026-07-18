"""Verify the full-screen Curator shell app."""

import asyncio

from textual.widgets import Input, Static

from curator.tui.reflow_log import ReflowRichLog
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


def test_shell_app_composer_does_not_overlap_status(tmp_path):
    """Verify the input box closes above the status bar without overlapping it."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            composer = app.query_one("#composer").region
            status = app.query_one("#status").region
            composer_bottom = composer.y + composer.height - 1
            assert composer_bottom < status.y, (
                f"composer bottom row {composer_bottom} overlaps status row {status.y}"
            )

    asyncio.run(run())


def test_shell_app_escape_closes_overlays_but_never_exits(tmp_path):
    """Verify Esc dismisses an open overlay when idle and never quits the app."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")  # idle, nothing open → no-op, not an exit
            await pilot.pause()
            assert not app.state.should_exit
            app.query_one("#input", Input).value = "/re"  # open the slash palette
            await pilot.pause()
            assert app.query_one("#palette").styles.display == "block"
            await pilot.press("escape")  # closes the palette instead of exiting
            await pilot.pause()
            assert app.query_one("#palette").styles.display == "none"
            assert not app.state.should_exit

    asyncio.run(run())


def test_shell_app_quit_word_exits(tmp_path):
    """Verify a bare quit/exit word closes the app, not just Ctrl+C."""

    async def run() -> None:
        for word in ("quit", "exit"):
            app = CuratorShellApp(project_root=tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#input", Input).value = word
                await pilot.press("enter")
                exited = False
                for _ in range(100):
                    await pilot.pause(0.05)
                    if app.state.should_exit:
                        exited = True
                        break
                assert exited, f"app did not exit on {word!r}"

    asyncio.run(run())


def test_shell_app_transcript_reflows_when_terminal_narrows(tmp_path):
    """Verify transcript text re-wraps to the terminal width instead of clipping."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._write(
                "A deliberately long transcript line that must re-wrap to the "
                "usable width when the terminal is made narrower rather than "
                "overflowing past the right edge and being clipped."
            )
            await pilot.pause()
            for width in (72, 50, 40):
                await pilot.resize_terminal(width, 20)
                await pilot.pause()
                log = app.query_one("#log", ReflowRichLog)
                assert log.virtual_size.width <= log.region.width, (
                    f"transcript overflows at width {width}: "
                    f"virtual={log.virtual_size.width} region={log.region.width}"
                )

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
            assert "eng:claude-code" in status
            assert "rev:claude-code" in status
            # Seats render once under their display labels — no duplicate
            # writer:/reviewer: entries.
            assert "writer:claude-code" not in status
            assert "reviewer:claude-code" not in status

    asyncio.run(run())


def test_shell_app_suggests_slash_completions(tmp_path):
    """Verify typing a slash prefix opens the borderless palette above the input."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#input", Input).value = "/pro"
            await pilot.pause()
            palette = app.query_one("#palette")
            assert palette.styles.display == "block"
            assert "/provider add claude-code" in app._palette_matches
            assert "/providers" in app._palette_matches

    asyncio.run(run())


def test_shell_app_quit_command_exits(tmp_path):
    """Verify /quit ends the app through the shared contract."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await _submit_and_wait(app, pilot, "/quit", "Bye.")
            assert app.state.should_exit

    asyncio.run(run())

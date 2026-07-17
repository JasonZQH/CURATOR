"""Verify full-screen input, startup gating, and interruption behavior."""

import asyncio
import threading

from textual.widgets import Input

import curator.tui.shell_app as shell_app_module
import curator.shell.repl as repl_module
from curator.providers.events import ProviderEvent, ProviderEventKind
from curator.providers.redact import redact_error
from curator.shell.repl import ShellResponse, ShellState, handle_shell_input
from curator.tui.shell_app import CuratorShellApp
from curator.tui.format import render_provider_event


def test_tui_idle_ctrl_c_exits(tmp_path):
    """Verify Ctrl+C exits an idle full-screen shell."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app.state.should_exit

    asyncio.run(run())


def test_tui_busy_esc_then_ctrl_c_waits_for_worker(monkeypatch, tmp_path):
    """Verify busy Esc cancels and the second interrupt drains the worker."""
    started = threading.Event()
    release = threading.Event()

    def blocking_dispatch(_state, _text):
        """Hold one fake dispatch until the test releases the worker."""
        started.set()
        release.wait(timeout=5)
        return ShellResponse("finished")

    monkeypatch.setattr(shell_app_module, "handle_shell_input", blocking_dispatch)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", Input)
            input_widget.value = "run"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if started.is_set():
                    break
            assert started.is_set()
            assert input_widget.disabled
            await pilot.press("escape")
            assert app.state.cancellation.cancelled
            await pilot.press("ctrl+c")
            assert app._shutdown_requested
            release.set()
            for _ in range(100):
                await pilot.pause(0.02)
                if app.state.should_exit:
                    break
            assert app.state.should_exit

    asyncio.run(run())


def test_tui_startup_gate_releases_after_preflight(monkeypatch, tmp_path):
    """Verify startup disables input until the worker finishes checks."""
    started = threading.Event()
    release = threading.Event()

    def slow_preflight(_project_root):
        """Hold the fake preflight until the test releases startup."""
        started.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setattr(shell_app_module, "_should_run_preflight", lambda: True)
    monkeypatch.setattr(shell_app_module, "run_preflight", slow_preflight)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", Input)
            for _ in range(50):
                await pilot.pause(0.02)
                if started.is_set():
                    break
            assert started.is_set()
            assert input_widget.disabled
            release.set()
            for _ in range(100):
                await pilot.pause(0.02)
                if not input_widget.disabled:
                    break
            assert not input_widget.disabled

    asyncio.run(run())


def test_tui_startup_failure_reenables_input_and_logs(monkeypatch, tmp_path):
    """Verify startup failures become visible without permanently blocking input."""
    monkeypatch.setattr(shell_app_module, "_should_run_preflight", lambda: True)

    def fail_reconcile(_project_root):
        """Raise a representative startup recovery failure."""
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(shell_app_module, "reconcile_project", fail_reconcile)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", Input)
            for _ in range(100):
                await pilot.pause(0.02)
                if not input_widget.disabled:
                    break
            assert not input_widget.disabled
            assert any("startup preflight" in block for block in app.transcript)

    asyncio.run(run())


def test_tui_tab_history_and_multiline_input(monkeypatch, tmp_path):
    """Verify completion, arrow history, and continuation-line submission."""
    (tmp_path / ".curator").mkdir()
    captured: list[str] = []

    def capture_dispatch(_state, text):
        """Capture one submitted TUI message without starting a provider."""
        captured.append(text)
        return ShellResponse("captured")

    monkeypatch.setattr(shell_app_module, "handle_shell_input", capture_dispatch)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", Input)
            input_widget.value = "/pro"
            await pilot.press("tab")
            assert input_widget.value == "/providers"
            await pilot.press("tab")
            assert input_widget.value == "/provider add claude-code"
            input_widget.value = "/help"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if captured:
                    break
            input_widget.value = ""
            await pilot.press("up")
            assert input_widget.value == "/help"
            input_widget.value = "first line"
            await pilot.press("shift+enter")
            input_widget.value = "second line"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if len(captured) == 2:
                    break
            assert captured[-1] == "first line\nsecond line"

    asyncio.run(run())


def test_provider_event_rendering_adds_safe_semantic_color() -> None:
    """Verify provider text is escaped while lifecycle events receive styles."""
    event = ProviderEvent(
        kind=ProviderEventKind.OUTPUT_CHUNK,
        provider_run_id="provider-1",
        payload={"text": "[bold]untrusted[/bold]"},
    )

    rendered = render_provider_event(event)

    assert rendered == "[white]\\[bold]untrusted\\[/bold][/white]"


def test_shell_input_guard_logs_unexpected_failures(monkeypatch, tmp_path) -> None:
    """Verify an unexpected REPL failure becomes a recoverable logged response."""

    def fail_natural_language(_state, _text):
        """Raise a representative application bug from shell dispatch."""
        raise KeyError("broken dispatch")

    monkeypatch.setattr(repl_module, "_handle_natural_language", fail_natural_language)

    response = handle_shell_input(ShellState(project_root=tmp_path), "run this")

    assert "recovered from an error" in response.text
    assert "shell input" in response.text
    error_log = tmp_path / ".curator" / "errors.log"
    assert error_log.exists()
    assert "broken dispatch" in error_log.read_text(encoding="utf-8")


def test_provider_error_redaction_covers_bare_api_tokens() -> None:
    """Verify a bare sk token cannot enter the provider error ledger."""
    redacted = redact_error("provider returned sk-1234567890abcdef1234567890")

    assert "sk-1234567890abcdef1234567890" not in redacted
    assert "[REDACTED]" in redacted

"""Verify full-screen input, startup gating, and interruption behavior."""

import asyncio
from contextlib import contextmanager
import threading

from textual.widgets import Input

import curator.tui.shell_app as shell_app_module
import curator.shell.repl as repl_module
from curator.providers.events import ProviderEvent, ProviderEventKind
from curator.providers.redact import redact_error, redact_secrets
from curator.shell.menus import proposal_menu
from curator.shell.repl import ShellResponse, ShellState, handle_shell_input
from curator.tui.shell_app import CuratorShellApp
from curator.tui.format import render_provider_event
from curator.tui.trust_screen import TrustScreen


def test_resume_and_revise_enter_project_lock_before_reading_pause(monkeypatch, tmp_path):
    """Verify pause-mutating shell commands serialize their complete operation."""
    lock_events: list[str] = []

    @contextmanager
    def recording_lock(_project_root):
        """Record the project-lock lifetime around a shell mutation."""
        lock_events.append("enter")
        try:
            yield
        finally:
            lock_events.append("exit")

    class DummyConnection:
        """Provide the close method required by the shell's read path."""

        def close(self) -> None:
            """Close the no-op test connection."""

    monkeypatch.setattr(repl_module, "project_write_lock", recording_lock)
    monkeypatch.setattr(repl_module, "_database_exists", lambda _state: True)
    monkeypatch.setattr(repl_module, "_connect_state", lambda _state: DummyConnection())
    monkeypatch.setattr(repl_module, "load_latest_pause_record", lambda *_args: None)

    state = ShellState(project_root=tmp_path)
    assert "No paused loop" in handle_shell_input(state, "/resume answer").text
    assert lock_events == ["enter", "exit"]

    lock_events.clear()
    assert "No paused loop" in handle_shell_input(state, "/revise new scope").text
    assert lock_events == ["enter", "exit"]


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
            assert not app.state.should_exit  # Esc interrupts, never exits
            await pilot.press("ctrl+c")  # first Ctrl+C asks to confirm
            assert not app._shutdown_requested
            await pilot.press("ctrl+c")  # second Ctrl+C force-exits
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


def test_redact_secrets_scrubs_without_trailing_truncation() -> None:
    """Verify redact_secrets removes credentials but, unlike redact_error, keeps the head."""
    text = "keep this leading text " + "x" * 600 + " sk-abcdef0123456789abcdef"

    scrubbed = redact_secrets(text)

    assert scrubbed.startswith("keep this leading text")
    assert "sk-abcdef0123456789abcdef" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_shell_history_file_and_load_stay_bounded(tmp_path):
    """Verify shell history stops growing without bound on disk and on load."""
    from curator.tui.prompt_input import (
        _MAX_HISTORY_ENTRIES,
        append_shell_history_entry,
        history_path,
        load_shell_history_entries,
    )

    (tmp_path / ".curator").mkdir()
    for index in range(_MAX_HISTORY_ENTRIES + 25):
        append_shell_history_entry(tmp_path, f"entry-{index}")

    entries = load_shell_history_entries(tmp_path)
    file_lines = history_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(entries) == _MAX_HISTORY_ENTRIES
    assert len(file_lines) == _MAX_HISTORY_ENTRIES
    assert entries[-1] == f"entry-{_MAX_HISTORY_ENTRIES + 24}"


def test_tui_transcript_stays_bounded(tmp_path):
    """Verify the plain-text transcript keeps only a bounded tail during long provider runs."""
    from curator.tui.shell_app import _MAX_TRANSCRIPT_ENTRIES

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.transcript = [f"old {index}" for index in range(_MAX_TRANSCRIPT_ENTRIES + 100)]
            app._write("newest line")
            assert len(app.transcript) == _MAX_TRANSCRIPT_ENTRIES
            assert app.transcript[-1] == "newest line"

    asyncio.run(run())


def test_tui_cancellation_token_rearms_for_the_next_run(monkeypatch, tmp_path):
    """Verify cancelling one run does not leave the shared token cancelled for later runs."""
    (tmp_path / ".curator").mkdir()
    observed_cancelled: list[bool] = []
    release = threading.Event()

    def dispatch(state, text):
        """Record the token state each run observes; block the first run so it can be cancelled."""
        observed_cancelled.append(state.cancellation.cancelled)
        if text == "first":
            release.wait(timeout=5)
        return ShellResponse("done")

    monkeypatch.setattr(shell_app_module, "handle_shell_input", dispatch)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", Input)
            input_widget.value = "first"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if observed_cancelled:
                    break
            assert observed_cancelled == [False]
            await pilot.press("escape")
            assert app.state.cancellation.cancelled
            release.set()
            for _ in range(100):
                await pilot.pause(0.02)
                if not app._busy:
                    break
            assert not app._busy
            input_widget.value = "second"
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.02)
                if len(observed_cancelled) == 2:
                    break
            assert len(observed_cancelled) == 2
            assert observed_cancelled[1] is False

    asyncio.run(run())


def test_tui_typed_text_over_open_menu_is_not_discarded(monkeypatch, tmp_path):
    """Verify typing a reply over an open proposal menu submits the text, not the highlighted option."""
    (tmp_path / ".curator").mkdir()
    captured: list[str] = []

    def dispatch(state, text):
        """Return a proposal menu for the first request; echo everything else."""
        captured.append(text)
        if text == "build a widget":
            return ShellResponse("Proposal ready", menu=proposal_menu())
        return ShellResponse("ok")

    monkeypatch.setattr(shell_app_module, "handle_shell_input", dispatch)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", Input)
            input_widget.value = "build a widget"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._menu is not None:
                    break
            assert app._menu is not None
            input_widget.value = "no, cancel that"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.02)
                if len(captured) == 2:
                    break
            assert captured[-1] == "no, cancel that"
            assert app._menu is None

    asyncio.run(run())


def test_tui_trust_screen_esc_exits(monkeypatch, tmp_path):
    """Verify Esc on the first-run trust modal exits, honoring its advertised 'Esc to exit'."""
    monkeypatch.setattr(shell_app_module, "_should_check_trust", lambda: True)
    monkeypatch.setattr(shell_app_module, "trust_decision", lambda _root: None)

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, TrustScreen)
            await pilot.press("escape")
            for _ in range(50):
                await pilot.pause(0.02)
                if app.state.should_exit:
                    break
            assert app.state.should_exit

    asyncio.run(run())

"""Run the full-screen Curator shell: log, input, and live status bar."""

import sys
import time
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.widgets import Input, RichLog, Static

from curator.diagnostics.preflight import render_preflight, run_preflight
from curator.providers.events import ProviderEvent
from curator.tui.format import escape_markup, render_provider_event
from curator.tui.prompt_input import (
    append_shell_history_entry,
    completion_matches,
    load_shell_history_entries,
)
from curator.scheduler.recovery import reconcile_project
from curator.shell.banner import render_banner
from curator.shell.onboarding import (
    build_welcome_text,
    first_run_needed,
    open_pause_exists,
    resolve_mode_for_project,
)
from curator.shell.repl import (
    KNOWN_SLASH_COMMANDS,
    ShellResponse,
    ShellState,
    _should_run_preflight,
    handle_shell_input,
)
from curator.shell.errors import recoverable_error_message
from curator.shell.wizard import run_setup_wizard
from curator.core.paths import build_curator_paths
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import load_provider_binding_for_role

_MAX_SUGGESTIONS = 6


class CuratorShellApp(App[None]):
    """Full-screen shell wrapping the line REPL's input contract."""

    CSS = """
    #log { height: 1fr; padding: 0 1; }
    #suggest { height: 1; padding: 0 1; color: $text-muted; }
    #status { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
    #input { dock: bottom; }
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
        Binding("escape", "interrupt", "Interrupt", priority=True),
    ]

    def __init__(self, project_root: Path | str, gate: bool = True) -> None:
        """Bind the app to one project root and shell state."""
        super().__init__()
        self.state = ShellState(project_root=Path(project_root), gate_mode=gate)
        self.transcript: list[str] = []
        self._busy = False
        self._busy_started_at: float | None = None
        self._spinner_index = 0
        self._interrupt_count = 0
        self._shutdown_requested = False
        self._startup_ready = not _should_run_preflight()
        self._history = load_shell_history_entries(project_root)
        self._history_index = len(self._history)
        self._continuation_lines: list[str] = []
        self._completion_index = 0
        self._completion_prefix: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the log, suggestion bar, input, and status bar."""
        yield RichLog(id="log", wrap=True, markup=True)
        yield Static("", id="suggest")
        yield Input(placeholder="Type what you want to work on, or /help", id="input")
        yield Static("", id="status")

    def on_mount(self) -> None:
        """Show the banner, kick off preflight, and focus the input."""
        self.state.emit_event = self._emit_provider_event
        self._write(render_banner(self.state.project_root))
        self._write("")
        if _should_run_preflight():
            self.run_worker(self._startup_preflight, thread=True)
        else:
            try:
                recovered = reconcile_project(self.state.project_root)
            except Exception as error:
                self._write(
                    recoverable_error_message(
                        self.state.project_root, "startup recovery", error
                    )
                )
                recovered = 0
            if recovered:
                self._write(f"Recovered {recovered} interrupted run(s).")
            self._write(build_welcome_text(self.state.project_root))
        self.query_one("#input", Input).disabled = not self._startup_ready
        self._refresh_status()
        self.query_one("#input", Input).focus()
        self.set_interval(0.2, self._refresh_busy_status)

    def _startup_preflight(self) -> None:
        """Run environment probes off the UI thread and report them."""
        try:
            recovered = reconcile_project(self.state.project_root)
            text = render_preflight(run_preflight(self.state.project_root))
            welcome = build_welcome_text(self.state.project_root)
            if recovered:
                text = f"Recovered {recovered} interrupted run(s).\n\n{text}"
            startup_text = f"{text}\n\n{welcome}"
        except Exception as error:
            startup_text = recoverable_error_message(
                self.state.project_root, "startup preflight", error
            )
        self.call_from_thread(self._finish_startup, startup_text)

    def _finish_startup(self, text: str) -> None:
        """Mark startup ready and display its diagnostics."""
        self._startup_ready = True
        self._write(text)
        self.query_one("#input", Input).disabled = False
        self.query_one("#input", Input).focus()

    def _write(self, text: str, markup: bool = False) -> None:
        """Append one safe or intentionally styled block to the TUI log."""
        self.transcript.append(text)
        self.query_one("#log", RichLog).write(text if markup else escape_markup(text))

    def _emit_provider_event(self, event: ProviderEvent) -> None:
        """Stream one provider progress line into the log."""
        self.call_from_thread(self._write, render_provider_event(event), True)

    def _status_text(self) -> str:
        """Build the persistent status line from durable state."""
        root = self.state.project_root
        mode = resolve_mode_for_project(root)
        parts = [mode.label]
        database = build_curator_paths(root).database
        if database.exists():
            connection = connect_database(database)
            try:
                initialize_database(connection)
                for seat in ("writer.default", "reviewer.default"):
                    binding = load_provider_binding_for_role(connection, seat)
                    bound = binding.provider_profile_id if binding else "unbound"
                    parts.append(f"{seat.split('.')[0]}:{bound}")
            finally:
                connection.close()
        parts.append("gate:on" if self.state.gate_mode else "gate:off")
        parts.append(root.name)
        text = " · ".join(parts)
        if self._busy and self._busy_started_at is not None:
            elapsed = time.monotonic() - self._busy_started_at
            frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self._spinner_index % 10]
            text = f"{frame} Working… {elapsed:.1f}s · Esc interrupts · {text}"
        if open_pause_exists(root):
            text = f"{text}  ⏸ paused — /resume · /revise · /cancel"
        return text

    def _refresh_status(self) -> None:
        """Re-render the bottom status bar."""
        self.query_one("#status", Static).update(self._status_text())

    def _refresh_busy_status(self) -> None:
        """Advance the spinner and refresh elapsed work time when busy."""
        if self._busy:
            self._spinner_index += 1
            self._refresh_status()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update slash-command suggestions while typing."""
        text = event.value.strip()
        suggest = self.query_one("#suggest", Static)
        if not text.startswith("/"):
            suggest.update("")
            self._completion_prefix = None
            self._completion_index = 0
            return
        matches = [
            command for command in KNOWN_SLASH_COMMANDS if command.startswith(text)
        ]
        suggest.update("  ".join(matches[:_MAX_SUGGESTIONS]))
        if self._completion_prefix is None or text not in completion_matches(self._completion_prefix):
            self._completion_prefix = text
            self._completion_index = 0

    def on_key(self, event: events.Key) -> None:
        """Handle TUI history, completion, and continuation-line shortcuts."""
        input_widget = self.query_one("#input", Input)
        if not input_widget.has_focus:
            return
        if event.key in {"up", "down"}:
            event.prevent_default()
            self._move_history(-1 if event.key == "up" else 1)
            return
        if event.key == "tab":
            prefix = self._completion_prefix or input_widget.value
            matches = completion_matches(prefix)
            if matches:
                event.prevent_default()
                input_widget.value = matches[self._completion_index % len(matches)]
                input_widget.cursor_position = len(input_widget.value)
                self._completion_index += 1
            return
        if event.key in {"shift+enter", "ctrl+j"}:
            event.prevent_default()
            if input_widget.value:
                self._continuation_lines.append(input_widget.value)
                input_widget.value = ""
                input_widget.placeholder = "Continuation line… press Enter to submit"

    def _move_history(self, direction: int) -> None:
        """Move the TUI input through persisted command history."""
        if not self._history:
            return
        self._history_index = max(
            0, min(len(self._history), self._history_index + direction)
        )
        value = "" if self._history_index == len(self._history) else self._history[self._history_index]
        input_widget = self.query_one("#input", Input)
        input_widget.value = value
        input_widget.cursor_position = len(value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dispatch one submitted line through the shell input contract."""
        text = event.value.strip()
        if self._continuation_lines:
            text = "\n".join([*self._continuation_lines, text]).strip()
            self._continuation_lines.clear()
            self.query_one("#input", Input).placeholder = "Type what you want to work on, or /help"
        self.query_one("#input", Input).value = ""
        if not text:
            return
        self._history.append(text)
        self._history = self._history[-100:]
        self._history_index = len(self._history)
        if build_curator_paths(self.state.project_root).curator_dir.exists():
            try:
                append_shell_history_entry(self.state.project_root, text)
            except OSError as error:
                self._write(
                    recoverable_error_message(
                        self.state.project_root, "TUI history", error
                    )
                )
        if not self._startup_ready:
            self._write("Startup checks are still running; input is temporarily disabled.")
            return
        if self._busy:
            self._write("Curator is busy — press Esc to interrupt the active run.")
            return
        self._write(f"› {text}")
        if text == "/setup":
            self._run_wizard()
            return
        self._busy = True
        self._busy_started_at = time.monotonic()
        self._spinner_index = 0
        self.query_one("#input", Input).disabled = True
        self._write("⠋ Working… (Esc interrupts)")
        self.run_worker(lambda: self._dispatch(text), thread=True, exclusive=True, group="dispatch")

    def _dispatch(self, text: str) -> None:
        """Run one shell input off the UI thread and render the response."""
        try:
            response = handle_shell_input(self.state, text)
        except Exception as error:
            response = ShellResponse(
                recoverable_error_message(self.state.project_root, "TUI dispatch", error)
            )
        self.call_from_thread(self._render_response, response)

    def _render_response(self, response: ShellResponse) -> None:
        """Write the response, refresh status, and honor exit requests."""
        if response.text:
            self._write(response.text)
        self._refresh_status()
        if response.should_exit:
            self.exit()
        self._busy = False
        self._busy_started_at = None
        self._interrupt_count = 0
        if not self._shutdown_requested:
            self.query_one("#input", Input).disabled = False
            self.query_one("#input", Input).focus()
        self._refresh_status()

    def action_interrupt(self) -> None:
        """Implement idle exit and two-stage busy cancellation semantics."""
        if not self._busy:
            self.state.should_exit = True
            self.exit()
            return
        self._interrupt_count += 1
        self.state.cancellation.cancel()
        self._write(
            "Cancellation requested. Press Ctrl+C again to exit."
            if self._interrupt_count == 1
            else "Stopping Curator…"
        )
        if self._interrupt_count >= 2:
            if self._shutdown_requested:
                return
            self._shutdown_requested = True
            self.query_one("#input", Input).disabled = True
            self.run_worker(
                self._wait_for_worker_and_reconcile,
                thread=True,
                exclusive=False,
                group="shutdown",
            )

    def _wait_for_worker_and_reconcile(self) -> None:
        """Wait up to five seconds, reconcile, and then close the TUI."""
        deadline = time.monotonic() + 5
        while self._busy and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            reconcile_project(self.state.project_root)
        except Exception as error:
            record = recoverable_error_message(
                self.state.project_root, "interrupt reconciliation", error
            )
            self.call_from_thread(self._write, record)
        self.call_from_thread(self._request_exit)

    def _request_exit(self) -> None:
        """Mark the shell exited before closing the Textual application."""
        self.state.should_exit = True
        self.exit()

    def _run_wizard(self) -> None:
        """Run the line-based setup wizard in a suspended terminal."""
        try:
            with self.suspend():
                outcome = run_setup_wizard(self.state.project_root)
        except SuspendNotSupported:
            self._write(
                "The setup wizard needs an interactive terminal — "
                "run `curator setup` outside the full-screen shell."
            )
            return
        self._write(outcome.message)
        self._refresh_status()


def run_shell_app(project_root: Path | str, gate: bool = True) -> None:
    """Offer first-run setup in plain terminal, then run the full-screen app."""
    _offer_first_run_wizard(project_root)
    CuratorShellApp(project_root=project_root, gate=gate).run()


def _offer_first_run_wizard(project_root: Path | str) -> None:
    """Run the setup wizard before the app takes over a fresh project."""
    if not first_run_needed(project_root) or not sys.stdin.isatty():
        return
    print(render_banner(project_root))
    print()
    print("This project is not initialized yet.")
    try:
        answer = input("Run the setup wizard now? [Y/n] ")
    except EOFError:
        return
    if answer.strip().lower() in {"", "y", "yes"}:
        print(run_setup_wizard(project_root).message)

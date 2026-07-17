"""Run the full-screen Curator shell with native onboarding and menus."""

import time
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from curator.core.paths import build_curator_paths
from curator.diagnostics.preflight import render_preflight, run_preflight
from curator.providers.events import ProviderEvent
from curator.scheduler.recovery import reconcile_project
from curator.shell.banner import render_banner, render_whats_new
from curator.shell.menus import MenuSpec
from curator.shell.modes import mode_for_gate, next_mode
from curator.shell.onboarding import build_welcome_text, first_run_needed, open_pause_exists, resolve_mode_for_project
from curator.shell.repl import (
    KNOWN_SLASH_COMMANDS,
    SLASH_COMMAND_SPECS,
    ShellResponse,
    ShellState,
    _should_run_preflight,
    handle_shell_input,
)
from curator.shell.errors import recoverable_error_message
from curator.shell.trust import _should_check_trust, record_trust_decision, trust_decision
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import load_provider_binding_for_role
from curator.tui.format import escape_markup, render_provider_event
from curator.tui.palette import SlashPalette
from curator.tui.prompt_input import append_shell_history_entry, completion_matches, load_shell_history_entries
from curator.tui.setup_screen import SetupScreen
from curator.tui.trust_screen import TrustScreen

_MAX_SUGGESTIONS = 6


class CuratorShellApp(App[None]):
    """Full-screen shell wrapping the line REPL's input contract."""

    CSS = """
    #header { height: 1; padding: 0 1; background: $panel; color: $text; }
    #log { height: 1fr; padding: 0 1; }
    #palette { layer: overlay; height: auto; max-height: 12; dock: bottom; margin: 0 1 4 1; display: none; background: $surface; border: round $accent; }
    #hints { height: 1; padding: 0 1; color: $text-muted; background: $panel; }
    #suggest { display: none; }
    #selection { layer: overlay; height: auto; max-height: 8; dock: bottom; margin: 0 1 4 1; display: none; background: $surface; border: round $accent; }
    #menu-title { layer: overlay; height: 1; dock: bottom; margin: 0 1 12 1; display: none; color: $text; }
    #status { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
    #input { dock: bottom; }
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
        Binding("escape", "interrupt", "Interrupt", priority=True),
        Binding("shift+tab", "cycle_mode", "Approval mode"),
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
        self._history: list[str] = []
        self._history_index = 0
        self._continuation_lines: list[str] = []
        self._completion_index = 0
        self._completion_prefix: str | None = None
        self._palette_matches: list[str] = []
        self._menu: MenuSpec | None = None
        self._menu_index = 0
        self._trust_required = _should_check_trust()

    def compose(self) -> ComposeResult:
        """Compose the header, transcript, palette, input, and footer chrome."""
        yield Static("", id="header")
        yield RichLog(id="log", wrap=True, markup=True)
        yield SlashPalette(id="palette")
        yield Static("", id="menu-title")
        yield OptionList(id="selection")
        yield Static("", id="hints")
        yield Static("", id="suggest")
        yield Input(placeholder="Type what you want to work on, or /help", id="input")
        yield Static("", id="status")

    def on_mount(self) -> None:
        """Show trust before project reads, then start checks and onboarding."""
        self.state.emit_event = self._emit_provider_event
        banner = render_banner(self.state.project_root)
        self.query_one("#header", Static).update(banner.splitlines()[-1])
        self._write(banner)
        self._write(render_whats_new())
        self.query_one("#input", Input).disabled = True
        self.set_interval(0.2, self._refresh_busy_status)
        decision = trust_decision(self.state.project_root) if self._trust_required else True
        if decision is None:
            self.push_screen(TrustScreen(), self._on_trust_decision)
        else:
            self._start_after_trust(decision)

    def _on_trust_decision(self, trusted: bool | None) -> None:
        """Persist the modal result and continue or exit without project access."""
        trusted = bool(trusted)
        record_trust_decision(self.state.project_root, trusted)
        if not trusted:
            self._write("Project not trusted. No project files were changed.")
            self.state.should_exit = True
            self.exit()
            return
        self._start_after_trust(True)

    def _start_after_trust(self, trusted: bool) -> None:
        """Load local shell state only after trust and begin startup work."""
        if not trusted:
            self._on_trust_decision(False)
            return
        self._history = load_shell_history_entries(self.state.project_root)
        self._history_index = len(self._history)
        if _should_run_preflight():
            self.run_worker(self._startup_preflight, thread=True, exclusive=True, group="startup")
        else:
            self._finish_startup(self._startup_without_preflight())

    def _startup_without_preflight(self) -> str:
        """Recover interrupted work and render the welcome text without probes."""
        try:
            recovered = reconcile_project(self.state.project_root)
        except Exception as error:
            return recoverable_error_message(self.state.project_root, "startup recovery", error)
        prefix = f"Recovered {recovered} interrupted run(s).\n\n" if recovered else ""
        return f"{prefix}{build_welcome_text(self.state.project_root)}"

    def _startup_preflight(self) -> None:
        """Run environment probes off the UI thread and return their report."""
        try:
            recovered = reconcile_project(self.state.project_root)
            def on_check(check) -> None:
                """Mirror one completed preflight check into the transcript."""
                mark = {"ok": "✓", "warn": "!", "fail": "✗"}.get(check.status, "?")
                self.call_from_thread(self._write, f"checking {check.key}… {mark}")

            report = run_preflight(self.state.project_root)
            for check in report.checks:
                on_check(check)
            text = render_preflight(report)
            if recovered:
                text = f"Recovered {recovered} interrupted run(s).\n\n{text}"
            startup_text = f"{text}\n\n{build_welcome_text(self.state.project_root)}"
        except Exception as error:
            startup_text = recoverable_error_message(self.state.project_root, "startup preflight", error)
        self.call_from_thread(self._finish_startup, startup_text)

    def _finish_startup(self, text: str) -> None:
        """Mark startup ready, render diagnostics, and open first-run setup."""
        self._startup_ready = True
        self._write(text)
        self._refresh_status()
        if self._trust_required and first_run_needed(self.state.project_root):
            self._open_setup()
            return
        self._enable_input()

    def _enable_input(self) -> None:
        """Enable and focus the prompt after startup or an overlay closes."""
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        input_widget.focus()

    def _write(self, text: str, markup: bool = False) -> None:
        """Append one safe or intentionally styled block to the TUI transcript."""
        self.transcript.append(text)
        self.query_one("#log", RichLog).write(text if markup else escape_markup(text))

    def _emit_provider_event(self, event: ProviderEvent) -> None:
        """Stream one provider progress line into the log."""
        self.call_from_thread(self._write, render_provider_event(event), True)

    def _status_text(self) -> str:
        """Build the persistent footer from durable mode and seat bindings."""
        root = self.state.project_root
        mode = resolve_mode_for_project(root)
        parts = [mode.label]
        database = build_curator_paths(root).database
        if database.exists():
            connection = connect_database(database)
            try:
                initialize_database(connection)
                seats = (
                    ("pm", "maindeck.default"),
                    ("eng", "writer.default"),
                    ("rev", "reviewer.default"),
                )
                bound: dict[str, str] = {}
                for label, seat in seats:
                    binding = load_provider_binding_for_role(connection, seat)
                    bound[label] = binding.provider_profile_id if binding else "unbound"
                    parts.append(f"{label}:{bound[label]}")
                if bound.get("eng") != "unbound":
                    parts.append(f"writer:{bound['eng']}")
                if bound.get("rev") != "unbound":
                    parts.append(f"reviewer:{bound['rev']}")
            finally:
                connection.close()
        parts.extend(("gate:on" if self.state.gate_mode else "gate:off", root.name))
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
        """Update the selectable slash palette and compact hint row."""
        text = event.value.strip()
        if not text.startswith("/") or self._menu is not None:
            self._hide_palette()
            self.query_one("#hints", Static).update("")
            self.query_one("#suggest", Static).update("")
            self._completion_prefix = None
            self._completion_index = 0
            return
        matches = [command for command in KNOWN_SLASH_COMMANDS if command.startswith(text)]
        self._palette_matches = matches[:_MAX_SUGGESTIONS]
        descriptions = dict(SLASH_COMMAND_SPECS)
        self.query_one("#hints", Static).update(
            "  ".join(f"{command} — {descriptions.get(command, '')}" for command in self._palette_matches)
        )
        self.query_one("#suggest", Static).update("  ".join(self._palette_matches))
        if self._palette_matches:
            palette = self.query_one("#palette", SlashPalette)
            palette.update_commands((command, descriptions.get(command, "")) for command in self._palette_matches)
            palette.styles.display = "block"
        else:
            self._hide_palette()
        if self._completion_prefix is None or text not in completion_matches(self._completion_prefix):
            self._completion_prefix = text
            self._completion_index = 0

    def _hide_palette(self) -> None:
        """Hide the slash palette without changing the prompt value."""
        self.query_one("#palette", SlashPalette).styles.display = "none"
        self._palette_matches = []

    def on_key(self, event: events.Key) -> None:
        """Handle menu navigation, history, completion, and multiline input."""
        input_widget = self.query_one("#input", Input)
        if not input_widget.has_focus:
            return
        if self._menu is not None and event.key in {"up", "down", "tab", "enter"}:
            event.prevent_default()
            if event.key in {"up", "down"}:
                self._menu_index = max(0, min(len(self._menu.options) - 1, self._menu_index + (1 if event.key == "down" else -1)))
                self.query_one("#selection", OptionList).highlighted = self._menu_index
            else:
                self._submit_menu_option()
            return
        if self._palette_matches and event.key in {"up", "down", "tab"}:
            event.prevent_default()
            if event.key in {"up", "down"}:
                self._completion_index = max(0, min(len(self._palette_matches) - 1, self._completion_index + (1 if event.key == "down" else -1)))
            else:
                self._accept_palette()
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

    def _accept_palette(self) -> None:
        """Copy the highlighted slash command into the input prompt."""
        prefix = self._completion_prefix or self.query_one("#input", Input).value
        matches = completion_matches(prefix)
        if not matches:
            return
        value = matches[self._completion_index % len(matches)]
        input_widget = self.query_one("#input", Input)
        input_widget.value = value
        input_widget.cursor_position = len(input_widget.value)
        self._completion_index += 1

    def _move_history(self, direction: int) -> None:
        """Move the TUI input through persisted command history."""
        if not self._history:
            return
        self._history_index = max(0, min(len(self._history), self._history_index + direction))
        value = "" if self._history_index == len(self._history) else self._history[self._history_index]
        input_widget = self.query_one("#input", Input)
        input_widget.value = value
        input_widget.cursor_position = len(value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dispatch one submitted line through the shared shell contract."""
        if self._menu is not None:
            self._submit_menu_option()
            return
        text = event.value.strip()
        if self._palette_matches and text not in KNOWN_SLASH_COMMANDS:
            self._accept_palette()
            text = self.query_one("#input", Input).value.strip()
        if self._continuation_lines:
            text = "\n".join([*self._continuation_lines, text]).strip()
            self._continuation_lines.clear()
            self.query_one("#input", Input).placeholder = "Type what you want to work on, or /help"
        self.query_one("#input", Input).value = ""
        self._submit_text(text)

    def _submit_text(self, text: str) -> None:
        """Record and dispatch one normalized prompt value."""
        if not text:
            return
        self._history.append(text)
        self._history = self._history[-100:]
        self._history_index = len(self._history)
        if build_curator_paths(self.state.project_root).curator_dir.exists():
            try:
                append_shell_history_entry(self.state.project_root, text)
            except OSError as error:
                self._write(recoverable_error_message(self.state.project_root, "TUI history", error))
        if not self._startup_ready:
            self._write("Startup checks are still running; input is temporarily disabled.")
            return
        if self._busy:
            self._write("Curator is busy — press Esc to interrupt the active run.")
            return
        self._write(f"› {text}")
        if text == "/setup":
            self._open_setup()
            return
        self._busy = True
        self._busy_started_at = time.monotonic()
        self._spinner_index = 0
        self.query_one("#input", Input).disabled = True
        self._write("⠋ Working… (Esc interrupts)")
        self.run_worker(lambda: self._dispatch(text), thread=True, exclusive=True, group="dispatch")

    def _open_setup(self) -> None:
        """Push the native setup overlay and pause prompt input until it closes."""
        self.query_one("#input", Input).disabled = True
        self.push_screen(SetupScreen(self.state.project_root), self._on_setup_finished)

    def _on_setup_finished(self, result) -> None:
        """Render setup completion and restore the shell footer and prompt."""
        if result is not None:
            self._write(result.message)
        self._refresh_status()
        self._enable_input()

    def _dispatch(self, text: str) -> None:
        """Run one shell input off the UI thread and render its response."""
        try:
            response = handle_shell_input(self.state, text)
        except Exception as error:
            response = ShellResponse(recoverable_error_message(self.state.project_root, "TUI dispatch", error))
        self.call_from_thread(self._render_response, response)

    def _render_response(self, response: ShellResponse) -> None:
        """Write a response, expose its menu, and honor exit requests."""
        if response.text:
            self._write(response.text)
        self._busy = False
        self._busy_started_at = None
        self._interrupt_count = 0
        if response.menu is not None:
            self._show_menu(response.menu)
        elif not self._shutdown_requested:
            self._enable_input()
        self._refresh_status()
        if response.should_exit:
            self.exit()

    def _show_menu(self, menu: MenuSpec) -> None:
        """Display a protocol-backed keyboard menu below the transcript."""
        self._menu = menu
        self._menu_index = 0
        title = self.query_one("#menu-title", Static)
        title.update(f"{menu.title}  ·  ↑/↓ choose · Enter confirm · Esc cancel")
        title.styles.display = "block"
        selection = self.query_one("#selection", OptionList)
        selection.set_options(Option(f"{index}) {option.label} — {option.description}", id=str(index - 1)) for index, option in enumerate(menu.options, 1))
        selection.highlighted = 0
        selection.styles.display = "block"
        self._hide_palette()
        self._enable_input()

    def _submit_menu_option(self) -> None:
        """Submit the selected menu option through the ordinary input protocol."""
        if self._menu is None:
            return
        option = self._menu.options[self._menu_index]
        self._close_menu()
        if option.submit_text == "edit ":
            input_widget = self.query_one("#input", Input)
            input_widget.value = "edit "
            input_widget.cursor_position = len(input_widget.value)
            self._enable_input()
            return
        self._submit_text(option.submit_text)

    def _close_menu(self) -> None:
        """Close a proposal menu and return keyboard focus to the prompt."""
        self._menu = None
        self.query_one("#selection", OptionList).styles.display = "none"
        self.query_one("#menu-title", Static).styles.display = "none"

    def action_cycle_mode(self) -> None:
        """Cycle proposal approval mode with Shift+Tab while idle."""
        if self._busy or self._menu is not None:
            return
        mode = next_mode(mode_for_gate(self.state.gate_mode))
        self.state.gate_mode = mode.value == "propose"
        self._write(f"Approval mode: {mode.value}")
        self._refresh_status()

    def action_interrupt(self) -> None:
        """Route Esc through overlays before idle exit or busy cancellation."""
        if self._menu is not None:
            self._close_menu()
            self._enable_input()
            return
        if self._palette_matches:
            self._hide_palette()
            return
        if not self._busy:
            self.state.should_exit = True
            self.exit()
            return
        self._interrupt_count += 1
        self.state.cancellation.cancel()
        self._write("Cancellation requested. Press Ctrl+C again to exit." if self._interrupt_count == 1 else "Stopping Curator…")
        if self._interrupt_count >= 2:
            if self._shutdown_requested:
                return
            self._shutdown_requested = True
            self.query_one("#input", Input).disabled = True
            self.run_worker(self._wait_for_worker_and_reconcile, thread=True, exclusive=False, group="shutdown")

    def _wait_for_worker_and_reconcile(self) -> None:
        """Wait up to five seconds, reconcile, and then close the TUI."""
        deadline = time.monotonic() + 5
        while self._busy and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            reconcile_project(self.state.project_root)
        except Exception as error:
            self.call_from_thread(self._write, recoverable_error_message(self.state.project_root, "interrupt reconciliation", error))
        self.call_from_thread(self._request_exit)

    def _request_exit(self) -> None:
        """Mark the shell exited before closing the Textual application."""
        self.state.should_exit = True
        self.exit()


def run_shell_app(project_root: Path | str, gate: bool = True) -> None:
    """Run the full-screen app without leaving it for onboarding prompts."""
    CuratorShellApp(project_root=project_root, gate=gate).run()

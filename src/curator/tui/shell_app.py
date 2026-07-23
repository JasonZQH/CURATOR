"""Run the full-screen Curator shell with native onboarding and menus."""

import sqlite3
import time
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from curator.core.paths import build_curator_paths
from curator.diagnostics.preflight import run_preflight
from curator.providers.events import ProviderEvent, ProviderEventKind
from curator.scheduler.recovery import reconcile_project
from curator import __version__
from curator.shell.banner import ASCII_BANNER, SLOGAN, WHATS_NEW, git_branch
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
from curator.tui.format import escape_markup, render_provider_event, user_echo
from curator.tui.palette import SlashPalette
from curator.tui.prompt_input import append_shell_history_entry, completion_matches, load_shell_history_entries
from curator.tui.reflow_log import ReflowRichLog
from curator.tui.setup_screen import SetupScreen
from curator.tui.trust_screen import TrustScreen

_MAX_SUGGESTIONS = 6

# Music-production words for each loop phase, so the busy indicator reads like producing a
# track rather than a flat "working". Keyed by LoopStepType value.
_PHASE_WORDS = {
    "plan": "Composing",
    "implement": "Arranging",
    "validate": "Mixing",
    "review": "Auditioning",
    "confirm": "Mastering",
}
_DEFAULT_PHASE_WORD = "Cueing up"


def _fmt_tokens(count: int) -> str:
    """Format a token count compactly for the working line, e.g. 1500 -> '1.5k'."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


# Streamed tool calls collapse into a single live block above the input (Claude Code's
# "⏺ tool(arg)" pattern): consecutive same-type calls stream a count + latest command there,
# and only a concise one-line summary lands in the scrollback transcript when the group ends.
_TOOL_GLYPH = "⏺"
_TOOL_ACCENT = "#ffc24b"
_TOOL_DIM = "#7e8bad"
_TOOL_DETAIL_CHARS = 68


def _one_line(text: str, limit: int = _TOOL_DETAIL_CHARS) -> str:
    """Collapse whitespace to a single line and truncate with an ellipsis."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
# Bound the plain-text transcript mirror so a long streamed run cannot grow it without
# limit (the on-screen log is already capped); mirrors the _history[-100:] cap.
_MAX_TRANSCRIPT_ENTRIES = 2000
# How long a forced exit waits for a cancelled worker to unwind and release the project
# lock before giving up and letting the next-launch reconcile recover the run.
_SHUTDOWN_DRAIN_SECONDS = 5.0


class CuratorShellApp(App[None]):
    """Full-screen shell wrapping the line REPL's input contract."""

    CSS = """
    Screen { background: ansi_default; }
    CuratorShellApp { background: ansi_default; }
    #log { height: 1fr; padding: 1 1 0 1; background: transparent; scrollbar-size: 0 0; }
    #footer { dock: bottom; height: auto; background: transparent; }
    #menu-title { height: 1; display: none; padding: 0 1; color: $text-muted; }
    #selection { height: auto; max-height: 8; display: none; padding: 0 1; background: transparent; border: none; }
    #selection:focus { border: none; }
    #selection > .option-list--option { padding: 0 1; }
    #selection > .option-list--option-highlighted { color: #eaf1ff; background: #24306a; text-style: bold; }
    #palette { height: auto; max-height: 10; display: none; padding: 0 1; background: transparent; border: none; }
    #palette:focus { border: none; }
    #palette > .option-list--option { padding: 0 1; }
    #palette > .option-list--option-highlighted { color: #eaf1ff; background: #24306a; text-style: bold; }
    #activity { height: auto; padding: 0 1; background: transparent; display: none; }
    #hints { height: auto; padding: 0 1; color: $text-muted; background: transparent; }
    #status { height: 1; padding: 0 1; background: transparent; color: $text-muted; }
    #composer { height: 3; margin: 0 1; padding: 0 1; background: transparent; border: round #2c3a6e; }
    #composer:focus-within { border: round #9dbcff; }
    #prompt-caret { width: 2; height: 1; color: #5b9bff; text-style: bold; }
    #input { width: 1fr; height: 1; padding: 0; background: transparent; border: none; }
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Quit", priority=True),
        Binding("escape", "escape", "Back", priority=True),
        Binding("shift+tab", "cycle_mode", "Approval mode"),
    ]

    def __init__(self, project_root: Path | str, gate: bool = True) -> None:
        """Bind the app to one project root and shell state."""
        # Enable native ANSI so an `ansi_default` background passes through to the
        # terminal (inheriting the user's Ghostty/iTerm background) instead of
        # being flattened to an opaque theme color by the truecolor filter.
        super().__init__(ansi_color=True)
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
        self._run_provider: str | None = None
        self._provider_tokens: dict[str, int] = {}
        self._tool_group_type: str | None = None
        self._tool_group_count = 0
        self._tool_group_detail = ""
        self._menu: MenuSpec | None = None
        self._menu_index = 0
        self._trust_required = _should_check_trust()
        self._status_connection: sqlite3.Connection | None = None

    def compose(self) -> ComposeResult:
        """Compose the transcript, overlays, input, and footer chrome."""
        yield ReflowRichLog(id="log")
        yield SetupScreen(self.state.project_root, self._on_setup_finished)
        with Vertical(id="footer"):
            yield Static("", id="menu-title")
            yield OptionList(id="selection")
            yield SlashPalette(id="palette")
            yield Static("", id="activity")
            yield Static("", id="hints")
            with Horizontal(id="composer"):
                yield Static("›", id="prompt-caret")
                # SuggestFromList shows the top matching command as dimmed ghost text;
                # Right-arrow / End accepts it (Tab still cycles the visible palette).
                yield Input(
                    placeholder="Type what you want to work on, or /help",
                    id="input",
                    suggester=SuggestFromList(KNOWN_SLASH_COMMANDS, case_sensitive=False),
                )
            yield Static("", id="status")

    def on_mount(self) -> None:
        """Show trust before project reads, then start checks and onboarding."""
        self.state.emit_event = self._emit_provider_event
        self.query_one("#input", Input).disabled = True
        self.set_interval(0.2, self._refresh_busy_status)
        decision = trust_decision(self.state.project_root) if self._trust_required else True
        if decision is True:
            self._start_after_trust(decision)
        else:
            self.push_screen(TrustScreen(self.state.project_root), self._on_trust_decision)

    def _on_trust_decision(self, trusted: bool | None) -> None:
        """Persist approval only and exit without locking out future launches."""
        trusted = bool(trusted)
        if not trusted:
            self._write("Project not trusted. No project files were changed.")
            self.state.should_exit = True
            self.exit()
            return
        record_trust_decision(self.state.project_root, True)
        self._start_after_trust(True)

    def _start_after_trust(self, trusted: bool) -> None:
        """Load local shell state only after trust and begin startup work."""
        if not trusted:
            self._on_trust_decision(False)
            return
        self._render_welcome()
        self._history = load_shell_history_entries(self.state.project_root)
        self._history_index = len(self._history)
        if _should_run_preflight():
            self.run_worker(self._startup_preflight, thread=True, exclusive=True, group="startup")
        else:
            self._finish_startup(self._startup_without_preflight())

    def _startup_without_preflight(self) -> str:
        """Recover interrupted work without probes; the welcome card carries guidance."""
        try:
            recovered = reconcile_project(self.state.project_root)
        except Exception as error:
            return recoverable_error_message(self.state.project_root, "startup recovery", error)
        return f"Recovered {recovered} interrupted run(s)." if recovered else ""

    def _startup_preflight(self) -> None:
        """Probe the environment off the UI thread, surfacing only problems."""
        try:
            recovered = reconcile_project(self.state.project_root)
            self.call_from_thread(self.query_one("#hints", Static).update, "Checking environment…")
            report = run_preflight(self.state.project_root)
            parts: list[str] = []
            if recovered:
                parts.append(f"Recovered {recovered} interrupted run(s).")
            issues = [check for check in report.checks if check.status != "ok"]
            if issues:
                marks = {"warn": "!", "fail": "✗"}
                lines = ["Environment needs attention:"]
                lines.extend(f"  {marks.get(c.status, '?')} {c.detail}" for c in issues)
                lines.append("Run /doctor for the full report and fixes.")
                parts.append("\n".join(lines))
            startup_text = "\n\n".join(parts)
        except Exception as error:
            startup_text = recoverable_error_message(self.state.project_root, "startup preflight", error)
        self.call_from_thread(self._finish_startup, startup_text)

    def _finish_startup(self, text: str) -> None:
        """Mark startup ready, render diagnostics, and open first-run setup."""
        self._startup_ready = True
        self.query_one("#hints", Static).update("")
        if text:
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

    def _write(
        self,
        text: str,
        markup: bool = False,
        transcript_text: str | None = None,
        fill: bool = False,
    ) -> None:
        """Append one safe or intentionally styled block to the TUI transcript."""
        self.transcript.append(text if transcript_text is None else transcript_text)
        if len(self.transcript) > _MAX_TRANSCRIPT_ENTRIES:
            self.transcript = self.transcript[-_MAX_TRANSCRIPT_ENTRIES:]
        content = text if markup else escape_markup(text)
        self.query_one("#log", ReflowRichLog).write_entry(content, fill=fill)

    def _render_welcome(self) -> None:
        """Render the two-column welcome card: wordmark + slogan, then getting-started + news."""
        from rich import box as rich_box
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        root = self.state.project_root
        branch = git_branch(root)
        home = str(Path.home())
        short = ("~" + str(root)[len(home) :]) if str(root).startswith(home) else root.name
        context = resolve_mode_for_project(root).label + " · " + short
        if branch:
            context += f" · git:{branch}"

        left = Text()
        left.append(f"{ASCII_BANNER}\n\n", style="#5b9bff")
        left.append("Plan with confidence.\nShip with evidence.\n\n", style="#b98bff")
        left.append(context, style="#5f7290")

        right = Text()
        right.append("Getting started\n", style="bold #b98bff")
        right.append(f"{build_welcome_text(root)}\n\n", style="#c8d8ff")
        right.append("What’s new\n", style="bold #b98bff")
        for item in WHATS_NEW:
            right.append(f"  • {item}\n", style="#8fa6d6")

        grid = Table.grid(padding=(0, 4))
        grid.add_column()
        grid.add_column()
        grid.add_row(left, right)

        panel = Panel(
            grid,
            title=f"curator v{__version__}",
            title_align="left",
            border_style="#5b9bff",
            box=rich_box.ROUNDED,
            padding=(0, 2),
            expand=False,
        )
        self._write_renderable(panel, f"curator v{__version__} · {short} · {SLOGAN}")

    def _write_renderable(self, renderable: object, transcript_text: str) -> None:
        """Write a Rich renderable to the log, keeping a plain-text transcript mirror."""
        self.transcript.append(transcript_text)
        self.query_one("#log", ReflowRichLog).write_entry(renderable)

    def _emit_provider_event(self, event: ProviderEvent) -> None:
        """Stream one provider progress line into the log (called from the worker thread)."""
        self.call_from_thread(self._on_provider_event, event)

    def _on_provider_event(self, event: ProviderEvent) -> None:
        """Record provider/token attribution on the UI thread, then render the event.

        Tool calls stream into one coalesced live block above the input; every other event
        first closes any open tool group (committing its summary) and writes to the log.
        """
        provider = event.payload.get("provider")
        if isinstance(provider, str) and provider:
            self._run_provider = provider
        tokens = event.payload.get("tokens")
        if isinstance(tokens, int) and self._run_provider:
            self._provider_tokens[self._run_provider] = (
                self._provider_tokens.get(self._run_provider, 0) + tokens
            )
        if event.kind is ProviderEventKind.TOOL_CALL:
            self._note_tool_call(event)
            return
        self._flush_tool_group()
        self._write(render_provider_event(event), True)

    def _note_tool_call(self, event: ProviderEvent) -> None:
        """Fold one tool call into the live activity block, coalescing same-type calls."""
        label = event.label or "tool"
        detail = str(event.payload.get("detail", "")).strip()
        if self._tool_group_type == label:
            self._tool_group_count += 1
            if detail:
                self._tool_group_detail = detail
        else:
            self._flush_tool_group()
            self._tool_group_type = label
            self._tool_group_count = 1
            self._tool_group_detail = detail
        self._render_tool_activity()

    def _render_tool_activity(self) -> None:
        """Update the live activity block for the current tool group (hidden when none)."""
        activity = self.query_one("#activity", Static)
        if self._tool_group_type is None:
            activity.update("")
            activity.styles.display = "none"
            return
        count = f" [{_TOOL_DIM}]×{self._tool_group_count}[/]" if self._tool_group_count > 1 else ""
        detail = _one_line(self._tool_group_detail)
        detail_part = f"  [{_TOOL_DIM}]{escape_markup(detail)}[/]" if detail else ""
        activity.update(
            f"[{_TOOL_ACCENT}]{_TOOL_GLYPH} {escape_markup(self._tool_group_type)}[/]"
            f"{count}{detail_part}"
        )
        activity.styles.display = "block"

    def _flush_tool_group(self) -> None:
        """Commit the current tool group to the transcript as one concise line, then clear."""
        if self._tool_group_type is None:
            return
        label, count, detail = self._tool_group_type, self._tool_group_count, self._tool_group_detail
        self._tool_group_type = None
        self._tool_group_count = 0
        self._tool_group_detail = ""
        head = f"[{_TOOL_ACCENT}]{_TOOL_GLYPH} {escape_markup(label)}[/]"
        if count > 1:
            summary = f"{head} [{_TOOL_DIM}]· {count} calls[/]"
        else:
            trimmed = _one_line(detail)
            summary = f"{head}  [{_TOOL_DIM}]{escape_markup(trimmed)}[/]" if trimmed else head
        self._write(summary, True)
        self._render_tool_activity()

    def _status_text(self) -> str:
        """Build the persistent footer from durable mode and seat bindings."""
        root = self.state.project_root
        mode = resolve_mode_for_project(root)
        parts = [mode.label]
        connection = self._status_ledger_connection()
        if connection is not None:
            seats = (
                ("pm", "maindeck.default"),
                ("eng", "writer.default"),
                ("rev", "reviewer.default"),
            )
            for label, seat in seats:
                binding = load_provider_binding_for_role(connection, seat)
                parts.append(f"{label}:{binding.provider_profile_id if binding else 'unbound'}")
        parts.extend(("gate:on" if self.state.gate_mode else "gate:off", root.name))
        text = " · ".join(parts)
        if open_pause_exists(root):
            text = f"{text}  ⏸ paused — /resume · /revise · /cancel"
        return text

    def _status_ledger_connection(self) -> sqlite3.Connection | None:
        """Return a cached read connection to the project ledger, initialized once.

        The status bar refreshes after every interaction, so opening a fresh connection
        and re-running the whole schema script each time is pure waste. Cache one
        connection (created on the UI thread and only ever read from here); its discrete
        autocommit SELECTs still observe the latest committed bindings.
        """
        if self._status_connection is not None:
            return self._status_connection
        database = build_curator_paths(self.state.project_root).database
        if not database.exists():
            return None
        connection = connect_database(database)
        initialize_database(connection)
        self._status_connection = connection
        return connection

    def _current_phase_word(self) -> str:
        """Return the music-production word for the loop step currently running.

        Reads the active iteration's step_type from the ledger so the indicator follows the
        real phase (plan/implement/verify/review), including the deterministic verify step
        that emits no provider event. Falls back to the default word between steps.
        """
        connection = self._status_ledger_connection()
        if connection is None:
            return _DEFAULT_PHASE_WORD
        try:
            row = connection.execute(
                "SELECT step_type FROM loop_iterations WHERE status = 'running' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return _DEFAULT_PHASE_WORD
        if row is None:
            return _DEFAULT_PHASE_WORD
        return _PHASE_WORDS.get(str(row[0]), _DEFAULT_PHASE_WORD)

    def _working_line(self) -> str:
        """Return the phase indicator shown just above the input, with provider token use."""
        frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self._spinner_index % 10]
        elapsed = 0.0 if self._busy_started_at is None else time.monotonic() - self._busy_started_at
        word = self._current_phase_word()
        tokens = self._provider_tokens.get(self._run_provider or "", 0)
        usage = (
            f" · {self._run_provider}: {_fmt_tokens(tokens)}"
            if self._run_provider and tokens
            else ""
        )
        return f"[#5b9bff]{frame}[/] {word}… {elapsed:.1f}s{usage} · Esc interrupts"

    def _refresh_status(self) -> None:
        """Re-render the bottom status bar."""
        self.query_one("#status", Static).update(self._status_text())

    def _refresh_busy_status(self) -> None:
        """Advance the spinner and refresh the above-input working indicator."""
        if self._busy:
            self._spinner_index += 1
            self.query_one("#hints", Static).update(self._working_line())

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update the selectable slash palette and compact hint row."""
        text = event.value.strip()
        if not text.startswith("/") or self._menu is not None:
            self._hide_palette()
            self._completion_prefix = None
            self._completion_index = 0
            return
        matches = [command for command in KNOWN_SLASH_COMMANDS if command.startswith(text)]
        self._palette_matches = matches[:_MAX_SUGGESTIONS]
        descriptions = dict(SLASH_COMMAND_SPECS)
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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Fill the input from a clicked slash-palette command so args can be typed next."""
        if event.option_list.id != "palette":
            return  # the setup/menu OptionList drives its own selection flow
        command = event.option_id
        if command is None:
            return
        input_widget = self.query_one("#input", Input)
        input_widget.value = command
        input_widget.cursor_position = len(command)
        input_widget.focus()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        """Handle menu navigation, history, completion, and multiline input."""
        input_widget = self.query_one("#input", Input)
        if not input_widget.has_focus:
            return
        if self._menu is not None and event.key in {"up", "down", "tab"}:
            event.prevent_default()
            if event.key in {"up", "down"}:
                self._menu_index = max(0, min(len(self._menu.options) - 1, self._menu_index + (1 if event.key == "down" else -1)))
                self.query_one("#selection", OptionList).highlighted = self._menu_index
            else:
                self._submit_menu_option()
            return
        # Enter is intentionally not intercepted here: it flows to on_input_submitted,
        # which accepts the highlighted option only when nothing was typed, so a typed
        # reply over the menu submits as text instead of running the highlighted option.
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
            if self._accept_palette():
                event.prevent_default()
            return
        if event.key in {"shift+enter", "ctrl+j"}:
            event.prevent_default()
            if input_widget.value:
                self._continuation_lines.append(input_widget.value)
                input_widget.value = ""
                input_widget.placeholder = "Continuation line… press Enter to submit"

    def _accept_palette(self) -> bool:
        """Copy the highlighted slash command into the input; return whether one applied."""
        prefix = self._completion_prefix or self.query_one("#input", Input).value
        matches = completion_matches(prefix)
        if not matches:
            return False
        value = matches[self._completion_index % len(matches)]
        input_widget = self.query_one("#input", Input)
        input_widget.value = value
        input_widget.cursor_position = len(input_widget.value)
        self._completion_index += 1
        return True

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
        text = event.value.strip()
        if self._menu is not None:
            # An empty Enter accepts the highlighted option (keyboard-menu path).
            # Any typed reply is the user's intent — never discard it to submit the
            # highlighted option (which would run "yes" when they typed "no").
            if not text:
                self._submit_menu_option()
                return
            self._close_menu()
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
        self._write(user_echo(text), markup=True, transcript_text=f"› {text}", fill=True)
        if text == "/setup":
            self._open_setup()
            return
        self._busy = True
        # Re-arm cancellation for this run; the token is shared across every run,
        # so a prior Esc/Ctrl+C must not carry into the one we are starting.
        self.state.cancellation.reset()
        self._busy_started_at = time.monotonic()
        self._spinner_index = 0
        self._run_provider = None
        self._provider_tokens = {}
        self._flush_tool_group()
        self.query_one("#input", Input).disabled = True
        self.query_one("#hints", Static).update(self._working_line())
        self.run_worker(lambda: self._dispatch(text), thread=True, exclusive=True, group="dispatch")

    def _open_setup(self) -> None:
        """Replace the whole bottom footer with the setup panel while it runs."""
        self.query_one("#footer", Vertical).styles.display = "none"
        self.query_one("#setup-panel", SetupScreen).open()

    def _on_setup_finished(self, result) -> None:
        """Render setup completion and restore the ordinary bottom prompt."""
        if result is not None:
            self._write(result.message)
        self.query_one("#footer", Vertical).styles.display = "block"
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
        self._flush_tool_group()
        if response.text:
            self._write(response.text)
        self._busy = False
        self._busy_started_at = None
        self._interrupt_count = 0
        self.query_one("#hints", Static).update("")
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

    def _close_open_overlay(self) -> bool:
        """Close an open setup panel, proposal menu, or slash palette if any is up."""
        if self.query_one("#setup-panel", SetupScreen)._open:
            self.query_one("#setup-panel", SetupScreen).cancel()
            return True
        if self._menu is not None:
            self._close_menu()
            self._enable_input()
            return True
        if self._palette_matches:
            self._hide_palette()
            return True
        return False

    def action_escape(self) -> None:
        """Esc dismisses a modal/overlay or interrupts a run — it never exits the app."""
        # The app-level Esc binding is priority, so it fires even while a pushed
        # modal (the first-run trust screen) is focused and would otherwise handle
        # its own Esc. Delegate to the modal so its advertised "Esc to exit" works.
        if isinstance(self.screen, TrustScreen):
            self.screen.dismiss(False)
            return
        if self._close_open_overlay():
            return
        if self._busy:
            self.state.cancellation.cancel()
            self._write("Cancellation requested — stopping the run.")

    def action_interrupt(self) -> None:
        """Ctrl+C closes an overlay, quits when idle, or two-stage cancels when busy."""
        if self._close_open_overlay():
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
        """Wait for the cancelled worker to unwind, reconcile if it released the project, then exit.

        Reconcile only runs once the dispatch worker has cleared ``_busy`` — which happens
        strictly after it releases the per-thread project lock. Reconciling while that worker
        still owns the lock would raise ProjectLockedError (this runs on a different thread) and
        would race a run that is genuinely still live; a worker still stuck at the deadline is
        left to the next-launch reconcile instead.
        """
        deadline = time.monotonic() + _SHUTDOWN_DRAIN_SECONDS
        while self._busy and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self._busy:
            try:
                reconcile_project(self.state.project_root)
            except Exception as error:
                self.call_from_thread(self._write, recoverable_error_message(self.state.project_root, "interrupt reconciliation", error))
        self.call_from_thread(self._request_exit)

    def _request_exit(self) -> None:
        """Mark the shell exited before closing the Textual application."""
        self.state.should_exit = True
        self.exit()

    def on_unmount(self) -> None:
        """Release the cached status ledger connection when the app closes."""
        if self._status_connection is not None:
            self._status_connection.close()
            self._status_connection = None


def run_shell_app(project_root: Path | str, gate: bool = True) -> None:
    """Run the full-screen app without leaving it for onboarding prompts."""
    CuratorShellApp(project_root=project_root, gate=gate).run()

"""Drive setup as a bottom-docked prompt panel inside the main TUI."""

from collections.abc import Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from curator.diagnostics.preflight import PreflightCheck, probe_provider
from curator.shell.wizard_flow import Ask, Done, Probe, Say, SetupFlow, WizardResult


class SetupScreen(Vertical):
    """Render setup in the prompt area without replacing the whole terminal."""

    DEFAULT_CSS = """
    SetupScreen {
        dock: bottom;
        width: 100%;
        height: auto;
        max-height: 45%;
        padding: 1 2 1 2;
        background: ansi_default;
        border-top: solid #5b9bff;
        display: none;
    }
    #setup-kicker { color: #5b9bff; text-style: bold; }
    #setup-log {
        height: auto;
        max-height: 8;
        margin-top: 1;
        background: transparent;
        scrollbar-size: 0 0;
    }
    #setup-options {
        width: 72;
        height: auto;
        max-height: 8;
        margin-top: 1;
        padding: 0;
        background: transparent;
        border: none;
    }
    #setup-options:focus { border: none; }
    #setup-options > .option-list--option {
        padding: 0 1;
        color: $text;
        background: transparent;
    }
    #setup-options > .option-list--option-highlighted {
        color: #eaf1ff;
        background: #24306a;
        text-style: bold;
    }
    #setup-footer { margin-top: 1; color: $text-muted; }
    """

    def __init__(
        self,
        project_root: Path | str,
        on_complete: Callable[[WizardResult], None],
    ) -> None:
        """Create a hidden setup panel backed by the shared setup flow."""
        super().__init__(id="setup-panel")
        self.flow = SetupFlow(project_root)
        self._on_complete = on_complete
        self._open = False

    def compose(self) -> ComposeResult:
        """Compose setup context, output, choices, and keyboard guidance."""
        yield Label("SETUP · TEAM + PROVIDERS", id="setup-kicker")
        yield RichLog(id="setup-log", wrap=True, markup=False)
        yield OptionList(id="setup-options")
        yield Static("↑/↓ select · Enter confirm · Esc cancel", id="setup-footer")

    def open(self) -> None:
        """Show the setup panel and start its first state-machine event."""
        self._open = True
        self.styles.display = "block"
        self._render_events(self.flow.start())

    def close(self, result: WizardResult | None = None) -> None:
        """Hide setup and return its terminal result to the shell app."""
        self._open = False
        self.styles.display = "none"
        if result is not None:
            self._on_complete(result)

    def cancel(self) -> None:
        """Cancel setup without writing project state."""
        self.close(WizardResult(False, "Setup cancelled — nothing was written."))

    def _render_events(self, events: tuple[Say | Ask | Probe | Done, ...]) -> None:
        """Render state-machine events and schedule provider probes."""
        log = self.query_one("#setup-log", RichLog)
        options = self.query_one("#setup-options", OptionList)
        options.clear_options()
        for event in events:
            if isinstance(event, Say):
                log.write(event.text)
            elif isinstance(event, Ask):
                log.write(event.prompt)
                options.add_options(
                    Option(f"{index}) {label}", id=str(index))
                    for index, label in enumerate(event.options, 1)
                )
                options.highlighted = 0
                options.focus()
            elif isinstance(event, Probe):
                log.write("Checking provider CLIs…")
                options.disabled = True
                self.run_worker(
                    lambda: self._probe(event.providers),
                    thread=True,
                    exclusive=True,
                    group="setup-probe",
                )
            elif isinstance(event, Done):
                self.close(event.outcome)

    def _probe(self, providers: tuple[str, ...]) -> None:
        """Probe providers off the UI thread and return results to the panel."""
        checks = [(key, probe_provider(key)) for key in providers]
        self.app.call_from_thread(self._finish_probe, checks)

    def _finish_probe(self, checks: list[tuple[str, PreflightCheck]]) -> None:
        """Resume setup after provider detection completes."""
        self.query_one("#setup-options", OptionList).disabled = False
        self._render_events(self.flow.set_probes(checks))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Advance the setup flow with the selected numbered option."""
        if self._open and event.option.id is not None:
            self._render_events(self.flow.advance(event.option.id))

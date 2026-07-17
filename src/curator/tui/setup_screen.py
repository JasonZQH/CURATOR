"""Drive the setup flow inside the full-screen Textual application."""

from pathlib import Path

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, RichLog
from textual.widgets.option_list import Option

from curator.diagnostics.preflight import PreflightCheck, probe_provider
from curator.shell.wizard_flow import Ask, Done, Probe, Say, SetupFlow, WizardResult


class SetupScreen(ModalScreen[WizardResult]):
    """Render setup choices without suspending or leaving the TUI."""

    CSS = """
    SetupScreen { align: center middle; }
    #setup-dialog { width: 84; height: auto; max-height: 90%; padding: 1 2; background: $surface; border: round $accent; }
    #setup-log { height: auto; max-height: 18; margin-bottom: 1; }
    #setup-options { height: auto; max-height: 10; }
    """

    def __init__(self, project_root: Path | str) -> None:
        """Create an overlay backed by the shared setup state machine."""
        super().__init__()
        self.flow = SetupFlow(project_root)

    def compose(self) -> ComposeResult:
        """Compose the setup transcript and keyboard option list."""
        yield Label("Curator setup", id="setup-dialog")
        yield RichLog(id="setup-log", wrap=True, markup=False)
        yield OptionList(id="setup-options")

    def on_mount(self) -> None:
        """Start the flow and focus its first choice."""
        self._render_events(self.flow.start())

    def _render_events(self, events: tuple[Say | Ask | Probe | Done, ...]) -> None:
        """Render state-machine events and schedule background probes."""
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
                self.run_worker(lambda: self._probe(event.providers), thread=True, exclusive=True)
            elif isinstance(event, Done):
                self.dismiss(event.outcome)

    def _probe(self, providers: tuple[str, ...]) -> None:
        """Probe providers off the UI thread and return results to the overlay."""
        checks = [(key, probe_provider(key)) for key in providers]
        self.app.call_from_thread(self._finish_probe, checks)

    def _finish_probe(self, checks: list[tuple[str, PreflightCheck]]) -> None:
        """Resume setup after provider detection completes."""
        self.query_one("#setup-options", OptionList).disabled = False
        self._render_events(self.flow.set_probes(checks))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Advance the flow with the selected numbered option."""
        if event.option.id is None:
            return
        self._render_events(self.flow.advance(event.option.id))

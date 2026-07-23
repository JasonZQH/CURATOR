"""Drive the shared setup flow from ordinary line-oriented terminal IO."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from curator.diagnostics.preflight import probe_provider
from curator.shell.wizard_flow import Ask, Done, Probe, Say, SetupFlow, WizardResult

AskFn = Callable[[str], str]
SayFn = Callable[[str], None]


@dataclass(frozen=True)
class WizardOutcome:
    """Describe whether the wizard applied changes and what to tell the user."""

    applied: bool
    message: str


def run_setup_wizard(
    project_root: Path | str, ask: AskFn = input, say: SayFn = print
) -> WizardOutcome:
    """Run the shared state machine through injectable line IO."""
    flow = SetupFlow(project_root, compact_line=True)
    try:
        events = flow.start()
        while True:
            for event in events:
                if isinstance(event, Say):
                    say(event.text)
                elif isinstance(event, Probe):
                    checks = [(key, probe_provider(key)) for key in event.providers]
                    events = flow.set_probes(checks)
                    break
                elif isinstance(event, Ask):
                    events = flow.advance(ask(f"{event.prompt}\n> "))
                    break
                elif isinstance(event, Done):
                    return _outcome(event.outcome)
            else:
                return WizardOutcome(False, "Setup cancelled — nothing was written.")
    except EOFError:
        if flow.stage == "confirm":
            events = flow.advance("")
            for event in events:
                if isinstance(event, Done):
                    return _outcome(event.outcome)
        return WizardOutcome(False, "Setup cancelled — nothing was written.")


def _outcome(result: WizardResult) -> WizardOutcome:
    """Adapt the shared flow result to the historical wizard return type."""
    return WizardOutcome(applied=result.applied, message=result.message)

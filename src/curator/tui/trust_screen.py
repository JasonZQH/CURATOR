"""Show the first-run project trust decision as a native Textual modal."""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option


class TrustScreen(ModalScreen[bool]):
    """Ask whether Curator may inspect and modify the current project."""

    BINDINGS = [Binding("escape", "cancel", "Exit")]

    CSS = """
    TrustScreen { align: left top; background: ansi_default; }
    #trust-content { width: 100%; height: 100%; padding: 2 3; }
    #trust-topline { height: 1; background: #d89b28; }
    #trust-eyebrow { margin-top: 2; color: #d89b28; text-style: bold; }
    #trust-path { margin-top: 1; color: $text; text-style: bold; }
    #trust-title { margin-top: 2; color: $text; text-style: bold; }
    #trust-body { width: 88%; margin-top: 1; color: $text-muted; }
    #trust-note { width: 88%; margin-top: 1; color: $text; }
    #trust-options {
        width: 72;
        height: auto;
        max-height: 6;
        margin: 2 0 0 0;
        padding: 0;
        background: transparent;
        border: none;
    }
    #trust-options:focus { border: none; }
    #trust-options > .option-list--option {
        padding: 0 1;
        color: $text;
        background: transparent;
    }
    #trust-options > .option-list--option-highlighted {
        color: #fff7df;
        background: #59400d;
        text-style: bold;
    }
    #trust-footer { margin-top: 2; color: $text-muted; }
    """

    def __init__(self, project_root: Path | str) -> None:
        """Bind the onboarding screen to the workspace being reviewed."""
        super().__init__()
        self.project_root = Path(project_root)

    def compose(self) -> ComposeResult:
        """Compose the trust explanation and two keyboard choices."""
        with Vertical(id="trust-content"):
            yield Static("", id="trust-topline")
            yield Label("ACCESSING WORKSPACE", id="trust-eyebrow")
            yield Label(str(self.project_root), id="trust-path")
            yield Label("Quick safety check: is this a project you trust?", id="trust-title")
            yield Static(
                "Curator will inspect this workspace and may write .curator state after you approve a goal.\n\n"
                "Review the folder before continuing if it came from someone else.",
                id="trust-body",
            )
            yield Static(
                "Trusting this workspace allows Curator to read project files, run configured checks, "
                "and call the provider CLI within the approval gates.",
                id="trust-note",
            )
            yield OptionList(
                Option("› 1. Yes, trust this project", id="yes"),
                Option("  2. No, exit for now", id="no"),
                id="trust-options",
            )
            yield Static("Enter to confirm · Esc to exit", id="trust-footer")

    def on_mount(self) -> None:
        """Focus the first trust decision for immediate keyboard use."""
        self.query_one("#trust-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the selected trust decision to the shell app."""
        self.dismiss(event.option.id == "yes")

    def action_cancel(self) -> None:
        """Dismiss trust onboarding without persisting a deny decision."""
        self.dismiss(False)

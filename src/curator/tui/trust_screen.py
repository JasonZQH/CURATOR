"""Show the first-run project trust decision as a native Textual modal."""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class TrustScreen(ModalScreen[bool]):
    """Ask whether Curator may inspect and modify the current project."""

    CSS = """
    TrustScreen { align: center middle; }
    #trust-dialog { width: 72; height: auto; padding: 2 3; background: $surface; border: round $accent; }
    #trust-options { height: 5; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        """Compose the trust explanation and two keyboard choices."""
        yield Label(
            "Trust this project?\n\n"
            "Curator will inspect the workspace and may write .curator state when you approve a goal.",
            id="trust-dialog",
        )
        yield OptionList(
            Option("Trust project", id="yes"),
            Option("Exit without touching project files", id="no"),
            id="trust-options",
        )

    def on_mount(self) -> None:
        """Focus the first trust decision for immediate keyboard use."""
        self.query_one("#trust-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the selected trust decision to the shell app."""
        self.dismiss(event.option.id == "yes")

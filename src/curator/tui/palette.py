"""Render the searchable slash-command palette."""

from collections.abc import Iterable

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

# The command reads as the action; the description is dimmed so it reads as a hint.
_COMMAND_STYLE = "bold #9dbcff"
_DESCRIPTION_STYLE = "#7e8bad"


class SlashPalette(OptionList):
    """Display slash commands with descriptions while the prompt is active."""

    def update_commands(self, commands: Iterable[tuple[str, str]]) -> None:
        """Replace palette entries with the current filtered command set."""
        options = []
        for command, description in commands:
            label = Text(command, style=_COMMAND_STYLE)
            if description:
                label.append("   ")
                label.append(description, style=_DESCRIPTION_STYLE)
            options.append(Option(label, id=command))
        self.set_options(options)

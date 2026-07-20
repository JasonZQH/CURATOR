"""Render the searchable slash-command palette."""

from collections.abc import Iterable

from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SlashPalette(OptionList):
    """Display slash commands with descriptions while the prompt is active."""

    def update_commands(self, commands: Iterable[tuple[str, str]]) -> None:
        """Replace palette entries with the current filtered command set."""
        self.set_options(
            Option(f"{command}  —  {description}", id=command)
            for command, description in commands
        )

"""Describe keyboard menus without coupling the shell protocol to Textual."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MenuOption:
    """Describe one selectable menu entry and the text it submits."""

    label: str
    submit_text: str
    description: str = ""


@dataclass(frozen=True)
class MenuSpec:
    """Describe a menu that can be rendered by a TUI or ignored by a line REPL."""

    title: str
    options: tuple[MenuOption, ...]


def proposal_menu() -> MenuSpec:
    """Return the proposal approval menu using the existing answer grammar."""
    return MenuSpec(
        title="Choose what to do with this proposal",
        options=(
            MenuOption("Start loop", "yes", "Accept the goal and run it"),
            MenuOption("Cancel", "no", "Discard the pending proposal"),
            MenuOption("Edit", "edit ", "Return focus to the input for an edit"),
        ),
    )

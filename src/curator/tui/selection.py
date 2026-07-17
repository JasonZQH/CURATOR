"""Reusable keyboard-first selection prompt for Textual overlays."""

from collections.abc import Callable, Sequence

from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SelectionPrompt(OptionList):
    """Render labelled options and call a callback after keyboard selection."""

    def __init__(
        self,
        options: Sequence[str],
        on_select: Callable[[int, str], None] | None = None,
        *,
        id: str | None = None,
    ) -> None:
        """Create a prompt with numbered, focusable options."""
        self._labels = tuple(options)
        self._on_select = on_select
        super().__init__(
            *(Option(f"{index}) {label}", id=str(index - 1)) for index, label in enumerate(options, 1)),
            id=id,
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Forward the selected option index and label to the host screen."""
        if self._on_select is None:
            return
        index = int(event.option.id or 0)
        self._on_select(index, self._labels[index])

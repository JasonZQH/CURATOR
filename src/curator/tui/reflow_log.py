"""A transcript log that re-wraps its content when the terminal is resized."""

from rich.console import RenderableType
from rich.text import Text
from textual.events import Resize
from textual.widgets import RichLog

_FILL_STYLE = "on #141a38"
# Bound the reflow cache so a long streamed run cannot grow memory without limit and
# so on_resize (which re-renders every retained entry) stays bounded rather than O(n).
_MAX_ENTRIES = 2000


class ReflowRichLog(RichLog):
    """RichLog that reflows stored content to the current width on resize.

    Stock RichLog lays each write out once at write-time width and never
    re-wraps, and its default ``min_width`` (78) forces content wider than a
    narrow terminal; together these truncate the transcript when the window is
    made smaller. This subclass keeps the written renderables and rewrites them
    whenever the usable width changes, so text reflows instead of being clipped.

    Entries flagged ``fill`` are drawn as a full-width highlight bar (used for
    user-message echoes) whose background spans the current usable width.
    """

    def __init__(self, *, id: str | None = None, min_width: int = 8) -> None:
        """Create a word-wrapping log with a small minimum render width."""
        super().__init__(id=id, wrap=True, markup=True, min_width=min_width, max_lines=_MAX_ENTRIES)
        self._entries: list[tuple[RenderableType, bool]] = []
        self._reflow_width = 0

    def write_entry(self, content: RenderableType, fill: bool = False) -> None:
        """Append one line or renderable and remember it so a resize can reflow it."""
        self._entries.append((content, fill))
        if len(self._entries) > _MAX_ENTRIES:
            del self._entries[:-_MAX_ENTRIES]
        self._render_entry(content, fill)

    def _render_entry(self, content: RenderableType, fill: bool) -> None:
        """Render one stored entry, filling the row width when it is a highlight."""
        if not isinstance(content, str):
            self.write(content)
            return
        if not fill:
            self.write(content)
            return
        text = Text.from_markup(content)
        text.style = _FILL_STYLE
        width = self.scrollable_content_region.width or self.size.width
        if width and text.cell_len < width:
            text.pad_right(width - text.cell_len)
        self.write(text)

    def on_resize(self, event: Resize) -> None:
        """Re-wrap all remembered content when the usable width changes."""
        super().on_resize(event)
        width = event.size.width
        if not width or width == self._reflow_width or not self._entries:
            return
        self._reflow_width = width
        self.clear()
        for content, fill in self._entries:
            self._render_entry(content, fill)

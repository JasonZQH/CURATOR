"""Format streaming provider output safely for Rich-backed terminal views."""

from rich.markup import escape

from curator.providers.events import ProviderEvent, ProviderEventKind

_EVENT_STYLES = {
    ProviderEventKind.STARTED: "cyan",
    ProviderEventKind.OUTPUT_CHUNK: "white",
    ProviderEventKind.TOOL_CALL: "yellow",
    ProviderEventKind.PERMISSION_REQUEST: "magenta",
    ProviderEventKind.USAGE: "dim",
    ProviderEventKind.COMPLETED: "green",
    ProviderEventKind.FAILED: "red",
}


def escape_markup(text: str) -> str:
    """Escape user or provider text before rendering it as Rich markup."""
    return escape(text)


def user_echo(text: str) -> str:
    """Return one submitted prompt line styled as a full-width highlight bar.

    The row background is supplied by the log's fill rendering; here we set the
    amber caret and bright message text that sit on top of it.
    """
    return f"[bold #5b9bff]›[/] [bold #c8d8ff]{escape_markup(text)}[/]"


def render_provider_event(event: ProviderEvent) -> str:
    """Render one provider event with escaped text and semantic Rich color."""
    style = _EVENT_STYLES.get(event.kind, "white")
    label = f" {escape_markup(event.label)}" if event.label else ""
    if event.kind is ProviderEventKind.OUTPUT_CHUNK:
        return f"[{style}]{escape_markup(str(event.payload.get('text', '')))}[/{style}]"
    return f"[{style}]{escape_markup(event.kind.value)}{label}[/{style}]"

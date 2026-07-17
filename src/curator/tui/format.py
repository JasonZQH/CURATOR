"""Format streaming provider output safely for Rich-backed terminal views."""

from rich.markup import escape

from curator.providers.events import ProviderEvent, ProviderEventKind


def escape_markup(text: str) -> str:
    """Escape user or provider text before rendering it as Rich markup."""
    return escape(text)


def render_provider_event(event: ProviderEvent) -> str:
    """Render one provider event with escaped labels and output text."""
    label = f" {escape_markup(event.label)}" if event.label else ""
    if event.kind is ProviderEventKind.OUTPUT_CHUNK:
        return escape_markup(str(event.payload.get("text", "")))
    return f"[{escape_markup(event.kind.value)}]{label}"

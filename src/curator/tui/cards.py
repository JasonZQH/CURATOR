"""Render compact semantic blocks used by the shell chrome."""

from rich.panel import Panel
from rich.text import Text


def titled_block(title: str, body: str) -> Panel:
    """Build a titled Rich panel for a durable transcript block."""
    return Panel(Text(body), title=title, border_style="bright_black")


def goal_card(summary: str, criteria: list[str]) -> Panel:
    """Build a compact goal card from a summary and its done criteria."""
    lines = [summary, "", *[f"• {criterion}" for criterion in criteria]]
    return titled_block("Goal", "\n".join(lines))

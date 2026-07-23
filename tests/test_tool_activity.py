"""Streamed tool calls coalesce into one live block and commit a concise summary.

Instead of one wrapped, repeated transcript line per tool call, same-type calls stream a
count + latest command into a live block above the input; only a one-line summary lands in
the scrollback when the group closes (a non-tool event, a new tool type, or the run ending).
"""

import asyncio

from textual.widgets import Static

from curator.providers.events import ProviderEvent, ProviderEventKind
from curator.tui.shell_app import _one_line, CuratorShellApp


def _tool(label: str, detail: str) -> ProviderEvent:
    """Return a TOOL_CALL event carrying a tool name and a command/path detail."""
    return ProviderEvent(
        kind=ProviderEventKind.TOOL_CALL,
        provider_run_id="p",
        sequence=0,
        label=label,
        payload={"detail": detail},
    )


def _text(value: str) -> ProviderEvent:
    """Return an OUTPUT_CHUNK text event (a non-tool event that closes a tool group)."""
    return ProviderEvent(
        kind=ProviderEventKind.OUTPUT_CHUNK,
        provider_run_id="p",
        sequence=1,
        payload={"text": value},
    )


def test_one_line_collapses_newlines_and_truncates():
    """Verify a multi-line command becomes one truncated line for display."""
    assert _one_line("git log\n  --oneline", 40) == "git log --oneline"
    long = "x" * 100
    out = _one_line(long, 20)
    assert len(out) == 20 and out.endswith("…")


def test_same_type_tool_calls_coalesce_without_spamming_the_transcript(tmp_path):
    """Verify consecutive same-type tool calls stream one live block, not per-call lines."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            before = len(app.transcript)
            app._on_provider_event(_tool("command_execution", "git log --oneline -6"))
            app._on_provider_event(_tool("command_execution", "ruff check src"))
            await pilot.pause()

            assert app._tool_group_type == "command_execution"
            assert app._tool_group_count == 2
            assert len(app.transcript) == before  # nothing committed to scrollback yet
            live = str(app.query_one("#activity", Static).render())
            assert "command_execution" in live and "×2" in live and "ruff check src" in live
            assert app.query_one("#activity", Static).display is True

    asyncio.run(run())


def test_non_tool_event_flushes_the_group_as_one_summary_line(tmp_path):
    """Verify a following non-tool event commits a single count summary and clears the block."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._on_provider_event(_tool("command_execution", "a"))
            app._on_provider_event(_tool("command_execution", "b"))
            app._on_provider_event(_text("done reviewing"))
            await pilot.pause()

            assert app._tool_group_type is None
            assert app.query_one("#activity", Static).display is False
            assert any("command_execution" in block and "2 calls" in block for block in app.transcript)

    asyncio.run(run())


def test_a_new_tool_type_flushes_the_previous_group(tmp_path):
    """Verify switching tool type commits the prior group and starts a fresh one."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._on_provider_event(_tool("command_execution", "pytest -q"))
            app._on_provider_event(_tool("file_change", "src/app.py"))
            await pilot.pause()

            assert app._tool_group_type == "file_change"
            assert app._tool_group_count == 1
            assert any("command_execution" in block for block in app.transcript)
            live = str(app.query_one("#activity", Static).render())
            assert "file_change" in live and "src/app.py" in live

    asyncio.run(run())


def test_single_tool_call_summary_keeps_its_command(tmp_path):
    """Verify a lone tool call commits a summary with its (truncated) command, no count."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._on_provider_event(_tool("command_execution", "ls -la"))
            app._on_provider_event(_text("ok"))
            await pilot.pause()

            summary = next(b for b in app.transcript if "command_execution" in b)
            assert "ls -la" in summary
            assert "calls" not in summary

    asyncio.run(run())

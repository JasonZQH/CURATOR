"""Verify the reflowing transcript log wraps text and fills highlight bars."""

import asyncio

from textual.app import App, ComposeResult

from curator.tui.reflow_log import ReflowRichLog


class _LogApp(App):
    """Minimal host app exposing one reflowing transcript log."""

    def compose(self) -> ComposeResult:
        """Mount a single reflowing log widget."""
        yield ReflowRichLog(id="log")


def test_fill_entry_spans_the_full_usable_width():
    """Verify a highlight-bar entry pads to the full width regardless of text length."""

    async def run() -> None:
        app = _LogApp()
        async with app.run_test(size=(60, 10)) as pilot:
            await pilot.pause()
            log = app.query_one(ReflowRichLog)
            log.write_entry("[bold]› quit[/]", fill=True)
            await pilot.pause()
            assert log.virtual_size.width == log.scrollable_content_region.width

    asyncio.run(run())


def test_entries_are_capped_to_bound_resize_and_memory_cost():
    """Verify the reflow cache keeps only a bounded tail so long runs stay bounded on resize."""
    from curator.tui.reflow_log import _MAX_ENTRIES

    async def run() -> None:
        app = _LogApp()
        async with app.run_test(size=(60, 10)) as pilot:
            await pilot.pause()
            log = app.query_one(ReflowRichLog)
            for index in range(_MAX_ENTRIES + 50):
                log.write_entry(f"line {index}")
            await pilot.pause()
            assert len(log._entries) == _MAX_ENTRIES
            assert log._entries[-1][0] == f"line {_MAX_ENTRIES + 49}"

    asyncio.run(run())


def test_narrowing_reflows_instead_of_clipping():
    """Verify long content re-wraps to the new width when the terminal shrinks."""

    async def run() -> None:
        app = _LogApp()
        async with app.run_test(size=(90, 10)) as pilot:
            await pilot.pause()
            log = app.query_one(ReflowRichLog)
            log.write_entry(
                "A long line written wide that must re-wrap when the terminal is "
                "narrowed rather than overflowing past the right edge and clipping."
            )
            await pilot.pause()
            await pilot.resize_terminal(46, 10)
            await pilot.pause()
            assert log.virtual_size.width <= log.region.width

    asyncio.run(run())

"""Verify thread-safe cancellation handoff between TUI and scheduler loops."""

import asyncio
import threading

from curator.scheduler.cancellation import CancellationToken


def test_cancel_before_bind_interrupts_the_bound_task() -> None:
    """Verify an early cancellation request is replayed when a task binds."""

    async def run() -> None:
        token = CancellationToken()
        token.cancel()

        async def wait_for_cancel() -> None:
            """Bind a task and wait until the token interrupts it."""
            token.bind()
            await asyncio.sleep(60)

        task = asyncio.create_task(wait_for_cancel())
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled()

    asyncio.run(run())


def test_foreign_thread_cancellation_uses_loop_threadsafe_callback() -> None:
    """Verify a UI-thread cancellation reaches a scheduler task safely."""

    async def run() -> None:
        token = CancellationToken()
        callback_seen = threading.Event()
        loop = asyncio.get_running_loop()
        original = loop.call_soon_threadsafe

        def record_callback(callback, *args):
            """Record the thread-safe scheduling boundary before forwarding it."""
            callback_seen.set()
            return original(callback, *args)

        loop.call_soon_threadsafe = record_callback  # type: ignore[method-assign]

        async def wait_for_cancel() -> None:
            """Bind a task and wait for cancellation from another thread."""
            token.bind()
            await asyncio.sleep(60)

        task = asyncio.create_task(wait_for_cancel())
        await asyncio.sleep(0)
        thread = threading.Thread(target=token.cancel)
        thread.start()
        thread.join()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert callback_seen.is_set()
        assert task.cancelled()

    asyncio.run(run())

"""Expose cooperative cancellation for scheduler and shell workers."""

import asyncio
import threading


class CancellationToken:
    """Coordinate cancellation requests across one scheduler task and its driver."""

    def __init__(self) -> None:
        """Create a token with no cancellation request."""
        self._cancelled = False
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        """Request cancellation and interrupt the bound task on its event loop."""
        with self._lock:
            self._cancelled = True
            task = self._task
            loop = self._loop
        if task is None or task.done() or loop is None:
            return
        if loop.is_running() and loop is _running_loop():
            task.cancel()
            return
        try:
            loop.call_soon_threadsafe(_cancel_task, task)
        except RuntimeError:
            # The loop may be shutting down; the durable flag still makes the
            # scheduler observe cancellation at its next cooperative boundary.
            return

    def bind(self, task: asyncio.Task | None = None) -> None:
        """Bind the token and schedule cancellation if it was requested early."""
        bound_task = task or asyncio.current_task()
        if bound_task is None:
            raise RuntimeError("CancellationToken.bind() requires an asyncio task")
        loop = bound_task.get_loop()
        with self._lock:
            self._task = bound_task
            self._loop = loop
            already_cancelled = self._cancelled
        if already_cancelled:
            _cancel_task(bound_task)

    def raise_if_cancelled(self) -> None:
        """Raise CancelledError when a cancellation request is pending."""
        if self.cancelled:
            raise asyncio.CancelledError


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """Return the event loop running on the calling thread, if any."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _cancel_task(task: asyncio.Task) -> None:
    """Cancel a task from its own event-loop callback."""
    if not task.done():
        task.cancel()

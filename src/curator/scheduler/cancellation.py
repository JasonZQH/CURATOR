"""Expose cooperative cancellation for scheduler and shell workers."""

import asyncio


class CancellationToken:
    """Coordinate cancellation requests across one scheduler task and its driver."""

    def __init__(self) -> None:
        """Create a token with no cancellation request."""
        self._cancelled = False
        self._task: asyncio.Task | None = None

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._cancelled

    def cancel(self) -> None:
        """Request cancellation and interrupt the bound asyncio task."""
        self._cancelled = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def bind(self, task: asyncio.Task | None = None) -> None:
        """Bind the token to the current or explicitly supplied asyncio task."""
        self._task = task or asyncio.current_task()

    def raise_if_cancelled(self) -> None:
        """Raise CancelledError when a cancellation request is pending."""
        if self._cancelled:
            raise asyncio.CancelledError

"""Remove common secret forms before provider errors enter the ledger."""

import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)
_MAX_ERROR_CHARS = 500


def redact_secrets(value: str | None) -> str:
    """Redact common credential patterns from text without truncating it."""
    text = value or ""
    for pattern in _SECRET_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            """Return one redacted match without retaining its secret value."""
            raw = match.group(0)
            if raw.lower().startswith("sk-"):
                return "[REDACTED]"
            if raw.lower().startswith("bearer"):
                return "Bearer [REDACTED]"
            key = raw.split(":", 1)[0].split("=", 1)[0].strip()
            return f"{key}=[REDACTED]"

        text = pattern.sub(replace, text)
    return text


def redact_error(value: str | None, limit: int = _MAX_ERROR_CHARS) -> str:
    """Redact credentials and cap a persisted provider error to its trailing chars."""
    return redact_secrets(value)[-limit:]


# Hold back the last few chars of the redacted stream so a credential still forming at a
# chunk boundary is never emitted before its whole match is visible. It only has to exceed
# the longest key token ("password") plus its separator, so 64 leaves generous headroom.
_STREAM_TAIL_HOLD_CHARS = 64
# Bound the working buffer so an enormous single step cannot make redaction super-linear.
# On overflow scrub() compacts to the trailing half of this window; a secret would have to
# span that half to straddle the cut, which no real credential does.
_STREAM_MAX_BUFFER_CHARS = 1 << 16


class StreamRedactor:
    """Redact secrets across streamed chunks, tolerating a secret split over a boundary.

    ``redact_secrets`` scrubs each chunk in isolation, so a credential whose characters
    land in two different OUTPUT_CHUNK events survives. This redactor accumulates the raw
    stream, redacts the whole buffer on every feed (so a boundary-spanning match is always
    seen intact), and emits only the portion that can no longer change — holding back a
    short tail where a match might still be forming. ``flush`` releases the remainder once
    the stream ends.
    """

    def __init__(self, hold: int = _STREAM_TAIL_HOLD_CHARS) -> None:
        """Create a redactor that holds back ``hold`` trailing chars between feeds."""
        self._buffer = ""
        self._emitted = 0
        self._hold = hold

    def scrub(self, text: str) -> str:
        """Accept the next raw chunk and return the newly-stable redacted delta."""
        self._buffer += text
        redacted = redact_secrets(self._buffer)
        stable = redacted[: -self._hold] if len(redacted) > self._hold else ""
        delta = stable[self._emitted :]
        self._emitted = len(stable)
        if len(self._buffer) > _STREAM_MAX_BUFFER_CHARS:
            # Compact the buffer so cost and memory stay bounded. ``_emitted`` counts
            # *redacted* chars already released, so the dropped prefix must be discounted
            # in the same coordinate space — dropping raw chars alone (and resetting
            # ``_emitted`` to 0) silently loses the redacted length difference between the
            # raw prefix and its scrubbed form. Keeping a generous suffix makes a match
            # straddling the cut vanishingly unlikely, matching the whole-buffer guarantee.
            keep = _STREAM_MAX_BUFFER_CHARS // 2
            dropped = self._buffer[:-keep]
            self._emitted -= len(redact_secrets(dropped))
            self._buffer = self._buffer[-keep:]
        return delta

    def flush(self) -> str:
        """Return any remaining redacted text once the stream ends, then reset."""
        delta = redact_secrets(self._buffer)[self._emitted :]
        self._buffer = ""
        self._emitted = 0
        return delta

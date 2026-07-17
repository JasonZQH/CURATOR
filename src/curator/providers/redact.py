"""Remove common secret forms before provider errors enter the ledger."""

import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"),
)
_MAX_ERROR_CHARS = 500


def redact_error(value: str | None, limit: int = _MAX_ERROR_CHARS) -> str:
    """Redact common credential patterns and cap persisted provider errors."""
    text = value or ""
    for pattern in _SECRET_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            """Return one redacted match without retaining its secret value."""
            raw = match.group(0)
            if raw.lower().startswith("bearer"):
                return "Bearer [REDACTED]"
            key = raw.split(":", 1)[0].split("=", 1)[0].strip()
            return f"{key}=[REDACTED]"

        text = pattern.sub(replace, text)
    return text[-limit:]

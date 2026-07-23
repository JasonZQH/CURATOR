"""Recognize a provider CLI's own usage/rate-limit signal and render it clearly.

Claude Code and Codex do not expose remaining quota programmatically, but when a run
actually hits the limit they say so in their error output — usually with a reset time.
Curator relays that message rather than inventing a threshold it cannot know. Matching is
deliberately tolerant: the exact wording varies by CLI version, so several phrasings map to
the same signal and an unmatched message simply falls through to the ordinary error path.
"""

import re

_LIMIT_MARKERS = re.compile(
    r"(usage[ -]?limit|rate[ -]?limit|too many requests|\bquota\b|"
    r"usage cap|limit reached|\b429\b)",
    re.IGNORECASE,
)
_RESET_PATTERNS = (
    re.compile(r"reset[s]?\s+(?:at\s+)?([0-9]{1,2}:[0-9]{2}\s*(?:[ap]m)?)", re.IGNORECASE),
    re.compile(
        r"(?:reset[s]?|try again|retry)\s+(?:in|after)\s+"
        r"([0-9]+\s*(?:seconds?|minutes?|hours?|s|m|h))",
        re.IGNORECASE,
    ),
)


def is_usage_limit(text: str | None) -> bool:
    """Return whether a provider error message reports a usage or rate limit."""
    return bool(text) and _LIMIT_MARKERS.search(text) is not None


def usage_limit_reset(text: str | None) -> str | None:
    """Return the reset hint (a time or duration) from a limit message, when present."""
    if not text:
        return None
    for pattern in _RESET_PATTERNS:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def usage_limit_message(provider_label: str, text: str | None) -> str:
    """Return one clear, provider-attributed usage-limit line, with a reset hint if found."""
    reset = usage_limit_reset(text)
    return f"{provider_label} usage limit reached" + (f" — resets {reset}" if reset else "")

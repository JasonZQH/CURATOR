"""Persist shell failures while keeping the interactive surface recoverable."""

from datetime import UTC, datetime
from pathlib import Path
import traceback

from curator.providers.redact import redact_error

_MAX_TRACEBACK_CHARS = 12_000


def record_shell_error(
    project_root: Path | str,
    component: str,
    error: BaseException,
) -> Path | None:
    """Append one redacted shell failure to the project error log."""
    path = Path(project_root) / ".curator" / "errors.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        trace = redact_error(traceback.format_exc(), limit=_MAX_TRACEBACK_CHARS)
        if not trace.strip():
            trace = redact_error(str(error), limit=_MAX_TRACEBACK_CHARS)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                f"[{datetime.now(UTC).isoformat()}] {component}:\n{trace}\n"
            )
        path.chmod(0o600)
        return path
    except OSError:
        return None


def recoverable_error_message(
    project_root: Path | str,
    component: str,
    error: BaseException,
) -> str:
    """Record one failure and return a concise user-facing recovery message."""
    path = record_shell_error(project_root, component, error)
    suffix = f" See {path} for details." if path is not None else ""
    return f"Curator recovered from an error in {component}: {error}.{suffix}"

"""Persist explicit project trust decisions outside project-local state."""

import json
import os
import sys
import tempfile
from pathlib import Path


def trust_store_path() -> Path:
    """Return the user-level trust decision file path."""
    home = Path(os.environ.get("CURATOR_HOME", Path.home() / ".curator"))
    return home / "trusted_projects.json"


def _project_key(project_root: Path | str) -> str:
    """Return a canonical path key for one trusted project."""
    return str(Path(project_root).expanduser().resolve())


def trust_decision(project_root: Path | str) -> bool | None:
    """Return a stored trust decision, or None for missing/corrupt data."""
    path = trust_store_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get(_project_key(project_root))
        return value if isinstance(value, bool) else None
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return None


def record_trust_decision(project_root: Path | str, trusted: bool) -> None:
    """Atomically save one user trust decision with owner-only permissions."""
    path = trust_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    payload[_project_key(project_root)] = bool(trusted)
    descriptor, temporary = tempfile.mkstemp(prefix="trusted_projects.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _should_check_trust() -> bool:
    """Return whether startup should show the trust screen in this terminal."""
    override = os.environ.get("CURATOR_TRUST", "").lower()
    if override == "force":
        return True
    if override == "skip":
        return False
    return sys.stdin.isatty()

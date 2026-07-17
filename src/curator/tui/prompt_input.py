"""Implement shell history, completion, and continuation-line input helpers."""

from pathlib import Path
from collections.abc import Callable

from curator.shell.repl import KNOWN_SLASH_COMMANDS

_MAX_HISTORY_ENTRIES = 100


def history_path(project_root: Path | str) -> Path:
    """Return the private shell history path for one project."""
    return Path(project_root) / ".curator" / "shell_history"


def load_shell_history(project_root: Path | str) -> None:
    """Load one project history file into readline when available."""
    import readline

    path = history_path(project_root)
    if path.exists():
        readline.read_history_file(str(path))


def save_shell_history(project_root: Path | str) -> None:
    """Save readline history with owner-only permissions."""
    import readline

    path = history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    readline.write_history_file(str(path))


def load_shell_history_entries(project_root: Path | str) -> list[str]:
    """Load recent history entries for the full-screen input widget."""
    path = history_path(project_root)
    if not path.exists():
        return []
    try:
        return [line.replace("\\n", "\n") for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, UnicodeError):
        return []


def append_shell_history_entry(project_root: Path | str, entry: str) -> None:
    """Append one escaped full-screen input entry with private permissions."""
    path = history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(entry.replace("\n", "\\n") + "\n")


def configure_shell_completion() -> None:
    """Register slash-command completion with readline."""
    import readline

    def complete(text: str, state: int) -> str | None:
        """Return one matching command for a readline completion request."""
        matches = [command for command in KNOWN_SLASH_COMMANDS if command.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")


def completion_matches(prefix: str) -> list[str]:
    """Return slash-command completions for one full-screen input prefix."""
    return [command for command in KNOWN_SLASH_COMMANDS if command.startswith(prefix)]


def read_multiline(
    prompt: str,
    input_fn: Callable[[str], str] = input,
) -> str:
    """Read backslash-continued lines and return one joined shell message."""
    lines = [input_fn(prompt)]
    while lines[-1].endswith("\\"):
        lines[-1] = lines[-1][:-1]
        lines.append(input_fn("... "))
    return "\n".join(lines)

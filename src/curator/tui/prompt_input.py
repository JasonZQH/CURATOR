"""Implement shell history, completion, and continuation-line input helpers."""

from pathlib import Path
from collections.abc import Callable

from curator.shell.repl import KNOWN_SLASH_COMMANDS


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


def configure_shell_completion() -> None:
    """Register slash-command completion with readline."""
    import readline

    def complete(text: str, state: int) -> str | None:
        """Return one matching command for a readline completion request."""
        matches = [command for command in KNOWN_SLASH_COMMANDS if command.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")


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

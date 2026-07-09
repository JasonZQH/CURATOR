"""Detect terminal-command-shaped shell input before goal intake."""

from dataclasses import dataclass

_PROVIDER_NAMES = ("claude-code", "claude", "codex")

# Multi-word curator subcommand shapes and their in-shell equivalents.
# None means the command only exists in the OS terminal.
_MULTI_WORD_COMMANDS: dict[tuple[str, ...], str | None] = {
    ("provider", "add"): "/provider add",
    ("provider", "list"): "/providers",
    ("contract", "validate"): None,
}

# Single-word curator subcommands and their in-shell equivalents.
_SINGLE_WORD_COMMANDS: dict[str, str | None] = {
    "init": "/init",
    "status": "/status",
    "help": "/help",
    "doctor": "/doctor",
    "reset": None,
}


@dataclass(frozen=True)
class CommandIntent:
    """Describe one shell input that looks like a terminal command."""

    original: str
    slash_equivalent: str | None = None
    terminal_command: str | None = None
    already_inside: bool = False
    unknown_subcommand: bool = False


def _meaningful_tokens(text: str) -> list[str]:
    """Return lowercased tokens with option flags stripped."""
    return [token.lower() for token in text.split() if not token.startswith("-")]


def _match_subcommand(tokens: list[str], original: str, explicit: bool) -> CommandIntent | None:
    """Match tokens against known curator subcommand shapes.

    `explicit` marks input that carried the `curator` prefix, which is
    command-shaped even when the subcommand is unknown.
    """
    if not tokens:
        return CommandIntent(original=original, already_inside=True) if explicit else None

    head = tuple(tokens[:2])
    if head in _MULTI_WORD_COMMANDS:
        slash = _MULTI_WORD_COMMANDS[head]
        argument = tokens[2] if len(tokens) == 3 else None
        expected_length = 3 if head == ("provider", "add") else 2
        if len(tokens) == expected_length and (argument is None or argument in _PROVIDER_NAMES):
            if slash is None:
                return CommandIntent(
                    original=original,
                    terminal_command=f"curator {' '.join(tokens)}",
                )
            suffix = f" {argument}" if argument else ""
            return CommandIntent(original=original, slash_equivalent=f"{slash}{suffix}")

    if len(tokens) == 1 and tokens[0] in _SINGLE_WORD_COMMANDS:
        slash = _SINGLE_WORD_COMMANDS[tokens[0]]
        if slash is None:
            return CommandIntent(
                original=original, terminal_command=f"curator {tokens[0]}"
            )
        return CommandIntent(original=original, slash_equivalent=slash)

    if explicit:
        return CommandIntent(original=original, unknown_subcommand=True)
    return None


def detect_cli_command(text: str) -> CommandIntent | None:
    """Return a CommandIntent when input looks like a terminal command."""
    tokens = _meaningful_tokens(text)
    if not tokens:
        return None
    if tokens[0] == "curator":
        return _match_subcommand(tokens[1:], text.strip(), explicit=True)
    return _match_subcommand(tokens, text.strip(), explicit=False)


def render_command_hint(intent: CommandIntent) -> str:
    """Return the guidance shown instead of treating a command as a task."""
    if intent.already_inside:
        return "\n".join(
            [
                "You are already inside the Curator shell.",
                "Type /help for commands, or describe what you want to work on.",
            ]
        )
    if intent.unknown_subcommand:
        return "\n".join(
            [
                f"That looks like a terminal command ({intent.original}), "
                "so it was not treated as a task — but there is no such curator subcommand.",
                "Type /help for shell commands.",
            ]
        )
    if intent.slash_equivalent is not None:
        return "\n".join(
            [
                "That looks like a terminal command, so it was not treated as a task.",
                "Inside the Curator shell use:",
                f"  {intent.slash_equivalent}",
            ]
        )
    return "\n".join(
        [
            "That looks like a terminal command, so it was not treated as a task.",
            f"`{intent.terminal_command}` runs outside this shell:",
            "exit with /quit, then run it in your OS terminal.",
        ]
    )

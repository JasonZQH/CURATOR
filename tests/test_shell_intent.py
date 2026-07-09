"""Verify command-shaped shell input is detected and redirected."""

from curator.shell.intent import CommandIntent, detect_cli_command, render_command_hint


def test_curator_prefixed_provider_add_maps_to_slash_command():
    """Verify the exact incident input maps to its slash equivalent."""
    intent = detect_cli_command("curator provider add claude-code")

    assert intent is not None
    assert intent.slash_equivalent == "/provider add claude-code"


def test_bare_provider_add_maps_to_slash_command():
    """Verify the curator prefix is not required for known command shapes."""
    intent = detect_cli_command("provider add codex")

    assert intent is not None
    assert intent.slash_equivalent == "/provider add codex"


def test_provider_list_maps_to_providers_view():
    """Verify provider list maps to the /providers shell view."""
    intent = detect_cli_command("curator provider list")

    assert intent is not None
    assert intent.slash_equivalent == "/providers"


def test_single_word_subcommands_map_to_slash_commands():
    """Verify bare init/status/help/doctor map to their shell commands."""
    assert detect_cli_command("init").slash_equivalent == "/init"
    assert detect_cli_command("status").slash_equivalent == "/status"
    assert detect_cli_command("help").slash_equivalent == "/help"
    assert detect_cli_command("curator doctor").slash_equivalent == "/doctor"


def test_terminal_only_commands_are_flagged_without_slash_equivalent():
    """Verify reset/contract validate are marked terminal-only."""
    for text in ("curator reset", "curator contract validate"):
        intent = detect_cli_command(text)
        assert intent is not None, text
        assert intent.slash_equivalent is None
        assert intent.terminal_command is not None


def test_bare_curator_is_flagged_as_already_inside_shell():
    """Verify typing just `curator` is intercepted with a notice."""
    intent = detect_cli_command("curator")

    assert intent is not None
    assert intent.already_inside


def test_unknown_curator_subcommand_is_still_intercepted():
    """Verify `curator <unknown>` never falls through to goal intake."""
    intent = detect_cli_command("curator frobnicate everything")

    assert intent is not None
    assert intent.slash_equivalent is None


def test_natural_language_is_not_intercepted():
    """Verify normal task descriptions never match the command detector."""
    for text in (
        "help me fix the login bug",
        "Fix mobile login layout",
        "add retry logic to the provider add flow",
        "status update copy for the release notes",
        "reset the password validation rules in signup",
    ):
        assert detect_cli_command(text) is None, text


def test_option_tokens_are_ignored_when_matching():
    """Verify flag arguments do not break command-shape matching."""
    intent = detect_cli_command("curator init --yes")

    assert intent is not None
    assert intent.slash_equivalent == "/init"


def test_render_command_hint_teaches_the_slash_form():
    """Verify the hint names the slash command and never starts a task."""
    intent = detect_cli_command("curator provider add claude-code")
    hint = render_command_hint(intent)

    assert "/provider add claude-code" in hint
    assert "not treated as a task" in hint


def test_render_command_hint_for_terminal_only_commands():
    """Verify terminal-only commands direct the user outside the shell."""
    intent = detect_cli_command("curator reset")
    hint = render_command_hint(intent)

    assert "curator reset" in hint
    assert "/quit" in hint


def test_render_command_hint_for_bare_curator():
    """Verify bare curator input explains the shell is already open."""
    hint = render_command_hint(detect_cli_command("curator"))

    assert "already inside" in hint.lower()


def test_command_intent_is_frozen_value_object():
    """Verify CommandIntent is immutable so hints cannot drift from detection."""
    intent = CommandIntent(original="curator status", slash_equivalent="/status")

    try:
        intent.slash_equivalent = "/help"
    except AttributeError:
        return
    raise AssertionError("CommandIntent should be immutable")

"""Verify the slash-command palette explains commands and supports quick fill.

The completion menu must describe what each command does (not a generic placeholder),
offer an inline ghost-text suggestion, and let a click fill the input.
"""

import asyncio

from textual.widgets import Input

from curator.shell.repl import KNOWN_SLASH_COMMANDS, SLASH_COMMAND_SPECS, _SLASH_DESCRIPTIONS
from curator.tui.palette import SlashPalette
from curator.tui.shell_app import CuratorShellApp


def test_every_known_slash_command_has_a_specific_description():
    """Verify no command falls back to the generic 'Run this Curator command' text."""
    missing = [command for command in KNOWN_SLASH_COMMANDS if command not in _SLASH_DESCRIPTIONS]
    assert not missing, f"slash commands without a description: {missing}"

    generic = [
        command for command, description in SLASH_COMMAND_SPECS
        if not description or description == "Run this Curator command"
    ]
    assert not generic, f"slash commands with a generic description: {generic}"


def test_argument_commands_hint_their_usage():
    """Verify commands that take arguments show the argument form in their description."""
    specs = dict(SLASH_COMMAND_SPECS)
    for command in ("/agent bind", "/agent switch", "/agent status", "/approve", "/resume"):
        assert "<" in specs[command], f"{command} should hint its arguments, got: {specs[command]!r}"


def test_palette_renders_specific_descriptions(tmp_path):
    """Verify typing a slash prefix shows the palette with real, per-command descriptions."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#input", Input).value = "/agent"
            await pilot.pause()
            palette = app.query_one("#palette", SlashPalette)
            assert palette.styles.display == "block"
            labels = [
                palette.get_option_at_index(i).prompt for i in range(palette.option_count)
            ]
            plain = "\n".join(getattr(label, "plain", str(label)) for label in labels)
            assert "Run this Curator command" not in plain
            assert "Bind a provider" in plain  # /agent bind carries a real description

    asyncio.run(run())


def test_input_offers_ghost_text_suggestion(tmp_path):
    """Verify the input has a suggester so a dimmed inline completion can appear."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#input", Input).suggester is not None

    asyncio.run(run())


def test_clicking_a_palette_command_fills_the_input(tmp_path):
    """Verify selecting a palette option copies that command into the input for quick fill."""

    async def run() -> None:
        app = CuratorShellApp(project_root=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#input", Input).value = "/work"
            await pilot.pause()
            palette = app.query_one("#palette", SlashPalette)
            option = palette.get_option_at_index(0)
            palette.post_message(SlashPalette.OptionSelected(palette, option, 0))
            await pilot.pause()
            assert app.query_one("#input", Input).value == "/workbench"

    asyncio.run(run())

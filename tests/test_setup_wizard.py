"""Verify the guided setup wizard: consent, providers, and zero pre-writes."""

import os

from typer.testing import CliRunner

from curator.cli import app
from curator.shell.onboarding import resolve_mode_for_project
from curator.shell.wizard import run_setup_wizard
from curator.core.paths import build_curator_paths
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    load_provider_binding_for_role,
    load_provider_profiles,
)


def _scripted(answers):
    """Return an ask() that pops scripted answers and EOFs when empty."""
    remaining = list(answers)

    def ask(prompt: str = "") -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return ask


def _fake_environment(tmp_path, monkeypatch, logged_in=True):
    """Install fake claude/codex binaries and a fake HOME on PATH."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("claude", "codex"):
        script = bin_dir / name
        script.write_text(
            "#!/usr/bin/env python3\n"
            f'print("{name} 9.9.9 (fake)")\n'
        )
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if logged_in:
        (home / ".claude").mkdir(exist_ok=True)
        (home / ".claude" / ".credentials.json").write_text("{}")
        (home / ".codex").mkdir(exist_ok=True)
        (home / ".codex" / "auth.json").write_text("{}")


def test_wizard_happy_path_binds_both_seats_and_goes_live(tmp_path, monkeypatch):
    """Verify the full wizard writes state, profiles, and both bindings."""
    _fake_environment(tmp_path, monkeypatch)
    said = []

    outcome = run_setup_wizard(
        tmp_path, ask=_scripted(["1", "1", "", "1"]), say=said.append
    )

    assert outcome.applied
    assert "Setup complete." in outcome.message
    assert "Mode: live" in outcome.message
    assert resolve_mode_for_project(tmp_path).label == "live"
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    profiles = load_provider_profiles(connection)
    writer = load_provider_binding_for_role(connection, "writer.default")
    reviewer = load_provider_binding_for_role(connection, "reviewer.default")
    connection.close()
    assert [profile.id for profile in profiles] == ["claude-code"]
    assert writer.provider_profile_id == "claude-code"
    assert reviewer.provider_profile_id == "claude-code"
    assert any("Step 1/3" in text for text in said)
    assert any("Step 2/3" in text for text in said)
    assert any("Step 3/3" in text for text in said)


def test_wizard_supports_distinct_providers_per_seat(tmp_path, monkeypatch):
    """Verify writer and reviewer can run on different providers."""
    _fake_environment(tmp_path, monkeypatch)

    outcome = run_setup_wizard(
        tmp_path, ask=_scripted(["1", "1", "2", "1"]), say=lambda _: None
    )

    assert outcome.applied
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    profiles = {profile.id for profile in load_provider_profiles(connection)}
    reviewer = load_provider_binding_for_role(connection, "reviewer.default")
    connection.close()
    assert profiles == {"claude-code", "codex"}
    assert reviewer.provider_profile_id == "codex"


def test_compact_setup_binds_engineer_prompt_pick_to_the_writer_seat(tmp_path, monkeypatch):
    """Verify the provider picked at the 'Engineer' prompt binds the writer seat, not just the reviewer."""
    _fake_environment(tmp_path, monkeypatch)

    # roles=default(1), PM=claude(1), Engineer prompt=codex(2), confirm=apply(1)
    outcome = run_setup_wizard(
        tmp_path, ask=_scripted(["1", "1", "2", "1"]), say=lambda _: None
    )

    assert outcome.applied
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    writer = load_provider_binding_for_role(connection, "writer.default")
    reviewer = load_provider_binding_for_role(connection, "reviewer.default")
    connection.close()
    # The pick made at the seat labelled "Engineer" must reach the engineer/writer seat.
    assert writer.provider_profile_id == "codex"
    assert reviewer.provider_profile_id == "codex"


def test_wizard_cancel_at_roles_step_writes_nothing(tmp_path, monkeypatch):
    """Verify cancelling at step one leaves the directory untouched."""
    _fake_environment(tmp_path, monkeypatch)

    outcome = run_setup_wizard(tmp_path, ask=_scripted(["2"]), say=lambda _: None)

    assert not outcome.applied
    assert "nothing was written" in outcome.message
    assert not (tmp_path / ".curator").exists()


def test_wizard_cancel_at_confirm_step_writes_nothing(tmp_path, monkeypatch):
    """Verify declining the final consent leaves the directory untouched."""
    _fake_environment(tmp_path, monkeypatch)

    outcome = run_setup_wizard(
        tmp_path, ask=_scripted(["1", "1", "", "2"]), say=lambda _: None
    )

    assert not outcome.applied
    assert not (tmp_path / ".curator").exists()


def test_wizard_eof_cancels_without_writes(tmp_path, monkeypatch):
    """Verify running out of input cancels instead of crashing."""
    _fake_environment(tmp_path, monkeypatch)

    outcome = run_setup_wizard(tmp_path, ask=_scripted([]), say=lambda _: None)

    assert not outcome.applied
    assert not (tmp_path / ".curator").exists()


def test_wizard_without_provider_clis_gives_install_guidance(tmp_path, monkeypatch):
    """Verify a machine without CLIs gets fixes, not a broken setup."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}{os.pathsep}/usr/bin{os.pathsep}/bin")

    outcome = run_setup_wizard(tmp_path, ask=_scripted(["1"]), say=lambda _: None)

    assert not outcome.applied
    assert "Install" in outcome.message
    assert not (tmp_path / ".curator").exists()


def test_wizard_warns_on_unverified_login_but_degrades(tmp_path, monkeypatch):
    """Verify unknown login state warns in the summary without blocking."""
    _fake_environment(tmp_path, monkeypatch, logged_in=False)
    said = []

    outcome = run_setup_wizard(
        tmp_path, ask=_scripted(["1", "1", "", "1"]), say=said.append
    )

    assert outcome.applied
    assert any("login state unknown" in text for text in said)


def test_shell_setup_command_runs_wizard_to_live_mode(tmp_path, monkeypatch):
    """Verify /setup drives the wizard end to end inside the shell."""
    _fake_environment(tmp_path, monkeypatch)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="/setup\n1\n1\n\n1\n/quit\n")

    assert result.exit_code == 0
    assert "Setup complete." in result.stdout
    assert resolve_mode_for_project(tmp_path).label == "live"


def test_curator_setup_command_runs_wizard(tmp_path, monkeypatch):
    """Verify the terminal `curator setup` entry point works."""
    _fake_environment(tmp_path, monkeypatch)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["setup"], input="1\n1\n\n1\n")

    assert result.exit_code == 0
    assert "Setup complete." in result.stdout


def test_provider_add_requires_initialized_state(tmp_path, monkeypatch):
    """Verify provider add no longer silently initializes the project."""
    _fake_environment(tmp_path, monkeypatch)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["provider", "add", "claude-code"])

    assert result.exit_code == 1
    assert "not initialized" in result.stdout
    assert not (tmp_path / ".curator").exists()


def test_shell_provider_add_requires_initialized_state(tmp_path, monkeypatch):
    """Verify /provider add points at /setup instead of writing state."""
    _fake_environment(tmp_path, monkeypatch)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="/provider add claude-code\n/quit\n")

    assert result.exit_code == 0
    assert "not initialized" in result.stdout
    assert "/setup" in result.stdout
    assert not (tmp_path / ".curator").exists()

"""Verify Curator command-line startup behavior."""

import tomllib
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agentctl.core.paths import build_curator_paths
from agentctl.cli import app


def test_curator_cli_starts_with_version():
    """Verify the packaged CLI entry point can start with the Curator name."""
    runner = CliRunner()

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "curator 0.1.0" in result.stdout


def test_pyproject_exposes_curator_and_legacy_agentctl_scripts():
    """Verify packaging exposes Curator while keeping the legacy agentctl alias."""
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["curator"] == "agentctl.cli:app"
    assert pyproject["project"]["scripts"]["agentctl"] == "agentctl.cli:app"


def test_legacy_agentctl_entrypoint_warns_to_use_curator():
    """Verify the legacy agentctl entrypoint tells users to use Curator."""
    runner = CliRunner()

    result = runner.invoke(app, [], input="/quit\n", prog_name="agentctl")

    assert result.exit_code == 0
    assert "agentctl is now Curator. Please use `curator`." in result.stdout


def test_bare_curator_opens_natural_language_shell(tmp_path, monkeypatch):
    """Verify bare curator starts the natural-language shell."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="/quit\n")

    assert result.exit_code == 0
    assert "Curator" in result.stdout
    assert "Type what you want to work on" in result.stdout


def test_shell_natural_language_fast_path_starts_loop_immediately(tmp_path, monkeypatch):
    """Verify small requests start and pause when no provider is configured."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="Fix mobile login layout\n/quit\n")

    assert result.exit_code == 0
    assert "Starting now: Fix mobile login layout" in result.stdout
    assert "Decision: human_handoff" in result.stdout
    assert "Start this loop?" not in result.stdout

    import sqlite3

    connection = sqlite3.connect(tmp_path / ".curator" / "curator.sqlite")
    approval_row = connection.execute(
        "select message from approval_decisions where approval_request_id = ?",
        ("approval-goal-goal-fix-mobile-login-layout",),
    ).fetchone()
    connection.close()
    assert approval_row is not None
    assert approval_row[0] == "auto-accepted (fast path)"


def test_shell_gate_mode_requires_proposal_review(tmp_path, monkeypatch):
    """Verify /gate on restores the propose/confirm ceremony."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, [], input="/gate on\nFix mobile login layout\n/quit\n"
    )

    assert result.exit_code == 0
    assert "PM drafted a goal contract:" in result.stdout
    assert "Start this loop? [yes/no/edit <instruction>]" in result.stdout
    assert "Starting now:" not in result.stdout


def test_shell_edit_updates_constraints_without_starting_loop(tmp_path, monkeypatch):
    """Verify shell edits append proposal constraints before loop execution."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [],
        input="/gate on\nFix mobile login layout\nedit Do not change auth flow\n/quit\n",
    )

    assert result.exit_code == 0
    assert "Do not change auth flow" in result.stdout
    assert (tmp_path / ".curator" / "curator.sqlite").exists()


def test_shell_edit_summary_rewrites_proposal(tmp_path, monkeypatch):
    """Verify edit summary rewrites the proposal summary instead of appending."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [],
        input=(
            "/gate on\n"
            "Fix mobile login layout\n"
            "edit summary Fix responsive login layout on mobile\n"
            "/quit\n"
        ),
    )

    assert result.exit_code == 0
    assert "Fix responsive login layout on mobile" in result.stdout


def test_shell_yes_accepts_goal_starts_loop_and_stores_run(tmp_path, monkeypatch):
    """Verify accepted shell proposals run the loop and persist goal linkage."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, [], input="/gate on\nFix mobile login layout\nyes\n/quit\n"
    )

    assert result.exit_code == 0
    assert "Goal accepted:" in result.stdout
    assert "Session:" in result.stdout
    assert "Decision: human_handoff" in result.stdout
    assert (tmp_path / ".curator" / "curator.sqlite").exists()


def test_shell_slash_commands_render_project_views(tmp_path, monkeypatch):
    """Verify shell slash commands route to existing product views."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [],
        input="/status\n/validate\nFix mobile login layout\n/node list\n/node current\n/quit\n",
    )

    assert result.exit_code == 0
    assert "Curator status" in result.stdout
    assert "Curator contract validate" in result.stdout
    assert "Session:" in result.stdout
    assert "Nodes:" in result.stdout
    assert "Node:" in result.stdout


def test_shell_runtime_workbench_commands_are_user_visible(tmp_path, monkeypatch):
    """Verify runtime readiness commands render through the real shell entrypoint."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [],
        input=(
            "/gate on\n"
            "Fix mobile login layout\n"
            "/agents\n"
            "/workbench\n"
            "yes\n"
            "/approvals\n"
            "/evidence\n"
            "/session current\n"
            "/quit\n"
        ),
    )

    assert result.exit_code == 0
    assert "PM drafted a goal contract:" in result.stdout
    assert "Agents:" in result.stdout
    assert "pm.coordinator" in result.stdout
    assert "Agent Runtime Workspace" in result.stdout
    assert "Runtime:" in result.stdout
    assert "Next Actions:" in result.stdout
    assert "Goal accepted:" in result.stdout
    assert "approval-goal-goal-fix-mobile-login-layout" in result.stdout
    assert "Evidence:" in result.stdout
    assert "Current session:" in result.stdout


def test_curator_init_prints_proposal_without_creating_state(tmp_path, monkeypatch):
    """Verify the init command previews state without writing files."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert not result.stdout.startswith("Curator Phase 0 CLI")
    assert "Curator init proposal" in result.stdout
    assert "Will create:" in result.stdout
    assert "- .curator/team/roles/pm/role.md" in result.stdout
    assert "- .curator/curator.sqlite" in result.stdout
    assert not (tmp_path / ".curator").exists()


def test_curator_init_accepts_explicit_project_root(tmp_path):
    """Verify the init command can preview a selected project root."""
    runner = CliRunner()
    (tmp_path / "package.json").write_text("{}\n")

    result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert not result.stdout.startswith("Curator Phase 0 CLI")
    assert f"Project root: {tmp_path}" in result.stdout
    assert "Detected project type: javascript" in result.stdout
    assert not (tmp_path / ".curator").exists()


def test_curator_doctor_reports_uninitialized_project(tmp_path, monkeypatch):
    """Verify doctor reports local setup without creating state."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Curator doctor" in result.stdout
    assert "State: missing" in result.stdout
    assert "Database: missing" in result.stdout
    assert "Recommended next step: curator init" in result.stdout
    assert not (tmp_path / ".curator").exists()


def test_curator_status_reports_initialized_project(tmp_path, monkeypatch):
    """Verify status reports initialized project state and session counts."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, [], input="Fix mobile login layout\n/quit\n")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Curator status" in result.stdout
    assert "Initialized: yes" in result.stdout
    assert "Sessions: 1" in result.stdout
    assert "Last session: session-" in result.stdout
    assert "Last decision: human_handoff" in result.stdout


def test_curator_status_reports_contract_warnings(tmp_path, monkeypatch):
    """Verify status surfaces editable contract fallback warnings."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--yes"])
    build_curator_paths(tmp_path).role_contract_file("engineer").write_text(
        "id: engineer\nhandoff_rules: [\n"
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Contract warnings:" in result.stdout
    assert "engineer" in result.stdout
    assert "invalid YAML" in result.stdout
    assert "fallback: yes" in result.stdout


def test_curator_contract_validate_reports_ok_for_default_contracts(tmp_path, monkeypatch):
    """Verify contract validate accepts generated default role contracts."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--yes"])

    result = runner.invoke(app, ["contract", "validate"])

    assert result.exit_code == 0
    assert "Curator contract validate" in result.stdout
    assert "Status: ok" in result.stdout
    assert "Contracts: 3" in result.stdout
    assert "Roles: engineer, pm, qa" in result.stdout
    assert "Handoff rules: " in result.stdout


def test_curator_contract_validate_reports_errors_for_bad_contracts(tmp_path, monkeypatch):
    """Verify contract validate fails fast with actionable contract errors."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--yes"])
    paths = build_curator_paths(tmp_path)
    parsed = yaml.safe_load(paths.role_contract_file("engineer").read_text())
    parsed["handoff_rules"][0]["to_role_id"] = "security"
    paths.role_contract_file("engineer").write_text(yaml.safe_dump(parsed, sort_keys=False))

    result = runner.invoke(app, ["contract", "validate"])

    assert result.exit_code == 1
    assert "Curator contract validate" in result.stdout
    assert "Status: failed" in result.stdout
    assert "engineer" in result.stdout
    assert "unknown handoff target" in result.stdout


def test_curator_demo_command_is_removed(tmp_path, monkeypatch):
    """Verify the removed demo command is no longer a user-facing entrypoint."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["demo", "--session-id", "session-demo-001"])

    assert result.exit_code != 0
    assert "No such command" in result.output


def test_curator_fake_run_option_is_removed(tmp_path, monkeypatch):
    """Verify top-level fake run options are no longer accepted."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--yes", "--fake-run", "--no-tui"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_curator_init_yes_creates_state(tmp_path, monkeypatch):
    """Verify the init command writes state only when explicitly approved."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0
    assert "Created Curator state" in result.stdout
    assert (tmp_path / ".curator" / "team" / "roles" / "pm" / "role.md").exists()
    assert (tmp_path / ".curator" / "memory" / "project.md").exists()
    assert (tmp_path / ".curator" / "curator.sqlite").exists()


def test_pyproject_declares_build_system():
    """Verify packaging declares a standard build backend for uvx/pipx installs."""
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())

    assert pyproject["build-system"]["build-backend"] == "hatchling.build"


def test_shell_welcome_banner_shows_mode_and_next_action(tmp_path, monkeypatch):
    """Verify the shell banner states the execution mode and one next action."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="/quit\n")

    assert result.exit_code == 0
    assert "Mode: setup" in result.stdout
    assert "Next:" in result.stdout
    assert "(setup) >" in result.stdout


def test_shell_help_is_task_oriented_with_full_list_fallback(tmp_path, monkeypatch):
    """Verify /help groups commands by task and /help all keeps the flat list."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="/help\n/help all\n/quit\n")

    assert result.exit_code == 0
    assert "What do you want to do?" in result.stdout
    assert "Start work:" in result.stdout
    assert "Watch progress:" in result.stdout
    assert "Handle pauses:" in result.stdout
    assert "Configure providers:" in result.stdout
    assert "Inspect history:" in result.stdout
    assert "Curator commands:" in result.stdout


def test_reset_requires_confirmation_and_reports_no_changes(tmp_path, monkeypatch):
    """Verify reset previews effects and does nothing without confirmation."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--yes"])

    result = runner.invoke(app, ["reset"], input="n\n")

    assert result.exit_code == 0
    assert "No changes made." in result.stdout
    assert (tmp_path / ".curator" / "curator.sqlite").exists()


def test_reset_archives_ledger_and_preserves_team_and_memory(tmp_path, monkeypatch):
    """Verify soft reset archives the database and keeps user-edited files."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--yes"])

    result = runner.invoke(app, ["reset", "--yes"])

    assert result.exit_code == 0
    curator_dir = tmp_path / ".curator"
    assert not (curator_dir / "curator.sqlite").exists()
    archives = list((curator_dir / "archive").glob("curator-*.sqlite"))
    assert len(archives) == 1
    assert (curator_dir / "team").exists()
    assert (curator_dir / "memory").exists()


def test_reset_hard_removes_entire_state_directory(tmp_path, monkeypatch):
    """Verify hard reset removes the whole .curator directory."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init", "--yes"])

    result = runner.invoke(app, ["reset", "--hard", "--yes"])

    assert result.exit_code == 0
    assert not (tmp_path / ".curator").exists()


def test_provider_add_rejects_fake_provider(tmp_path, monkeypatch):
    """Verify `curator provider add fake` is rejected."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    add_result = runner.invoke(app, ["provider", "add", "fake"])

    assert add_result.exit_code == 1
    assert "Unknown provider" in add_result.stdout


def test_provider_add_rejects_unknown_provider(tmp_path, monkeypatch):
    """Verify an unknown provider name exits non-zero with guidance."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["provider", "add", "gpt5"])

    assert result.exit_code == 1
    assert "Unknown provider" in result.stdout


def test_curator_init_interactive_confirm_creates_state(tmp_path, monkeypatch):
    """Verify init writes state after an interactive yes confirmation."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"], input="y\n")

    assert result.exit_code == 0
    assert "Curator init proposal" in result.stdout
    assert "Created Curator state" in result.stdout
    assert (tmp_path / ".curator" / "curator.sqlite").exists()


def test_curator_init_interactive_decline_leaves_no_state(tmp_path, monkeypatch):
    """Verify declining the init confirmation writes nothing."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"], input="n\n")

    assert result.exit_code == 0
    assert "No changes made" in result.stdout
    assert not (tmp_path / ".curator").exists()


def test_shell_init_command_initializes_project(tmp_path, monkeypatch):
    """Verify the /init slash command creates Curator state in-session."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, [], input="/init\n/quit\n")

    assert result.exit_code == 0
    assert "Initialized Curator state" in result.stdout
    assert (tmp_path / ".curator" / "curator.sqlite").exists()

"""Provide the Typer command-line adapter for Curator startup."""

from pathlib import Path

import typer

from agentctl import __version__
from agentctl.core.paths import build_curator_paths
from agentctl.app import (
    preview_init,
    write_init_state,
)
from agentctl.init.reset import (
    build_reset_summary,
    render_reset_summary,
    reset_curator_state,
)
from agentctl.diagnostics.doctor import inspect_project_health
from agentctl.diagnostics.status import inspect_project_status
from agentctl.rendering.terminal import (
    render_contract_validation_report,
    render_doctor_report,
    render_status_report,
)
from agentctl.providers.setup import add_provider_profile
from agentctl.shell.repl import run_interactive_shell
from agentctl.state.db import connect_database, initialize_database
from agentctl.state.repositories import load_provider_profiles
from agentctl.team.roles import validate_role_contracts

app = typer.Typer(
    add_completion=False,
    help="Curator local agent workbench.",
)
contract_app = typer.Typer(
    add_completion=False,
    help="Inspect and validate editable role contracts.",
)
provider_app = typer.Typer(
    add_completion=False,
    help="Connect and inspect provider profiles.",
)
app.add_typer(contract_app, name="contract")
app.add_typer(provider_app, name="provider")


def _version_callback(show_version: bool) -> None:
    """Print the package version and exit when requested."""
    if show_version:
        typer.echo(f"curator {__version__}")
        raise typer.Exit()


def _echo_init_write_summary(root: Path) -> None:
    """Print the approved init write summary for a project root."""
    result = write_init_state(root)
    _echo_init_summary(result.created_files_count, result.skipped_files_count)


def _echo_init_summary(created_files_count: int, skipped_files_count: int) -> None:
    """Print a Curator init summary from explicit counts."""
    typer.echo("Created Curator state")
    typer.echo(f"Created files: {created_files_count}")
    typer.echo(f"Skipped existing files: {skipped_files_count}")


def _ensure_curator_state(root: Path, yes: bool) -> None:
    """Create Curator state when requested or raise for interactive approval."""
    if not yes:
        typer.echo(preview_init(root))
        raise typer.Exit()

    _echo_init_write_summary(root)


@app.callback(invoke_without_command=True)
def main(
    context: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the Curator version and exit.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Approve non-interactive setup for top-level workflows.",
    ),
    no_tui: bool = typer.Option(
        False,
        "--no-tui",
        help="Print workflow output instead of launching the TUI.",
    ),
    gate: bool = typer.Option(
        False,
        "--gate",
        help="Require proposal review before every request runs.",
    ),
) -> None:
    """Start the Curator CLI shell for the current project."""
    _ = version
    if context.info_name == "agentctl":
        typer.echo("agentctl is now Curator. Please use `curator`.")

    _ = yes
    _ = no_tui

    if context.invoked_subcommand is None:
        run_interactive_shell(Path.cwd(), gate=gate)


@app.command("init")
def init_command(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        "-C",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project directory to inspect.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Create the proposed Curator state without interactive confirmation.",
    ),
) -> None:
    """Preview the Curator files that init would create, then optionally write."""
    root = project_root or Path.cwd()
    if yes:
        _echo_init_write_summary(root)
        return

    typer.echo(preview_init(root))
    try:
        confirmed = typer.confirm("Create these files now?", default=False)
    except typer.Abort:
        typer.echo("No changes made. Run curator init --yes to apply.")
        return
    if not confirmed:
        typer.echo("No changes made. Run curator init --yes to apply.")
        return
    _echo_init_write_summary(root)


@app.command("reset")
def reset_command(
    hard: bool = typer.Option(
        False,
        "--hard",
        help="Remove the entire .curator directory including team and memory files.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Reset without interactive confirmation.",
    ),
) -> None:
    """Archive the ledger and clear runtime state for this project."""
    root = Path.cwd()
    preview = build_reset_summary(root, hard=hard)
    typer.echo(render_reset_summary(preview, applied=False))
    if not preview.removed_paths and preview.archived_database is None:
        return

    if not yes:
        try:
            confirmed = typer.confirm("Reset Curator state now?", default=False)
        except typer.Abort:
            confirmed = False
        if not confirmed:
            typer.echo("No changes made.")
            return

    summary = reset_curator_state(root, hard=hard)
    typer.echo(render_reset_summary(summary, applied=True))


@app.command("doctor")
def doctor_command() -> None:
    """Inspect local Curator setup without changing project state."""
    typer.echo(render_doctor_report(inspect_project_health(Path.cwd())))


@app.command("status")
def status_command() -> None:
    """Show the current Curator project state without changing files."""
    typer.echo(render_status_report(inspect_project_status(Path.cwd())))


@contract_app.command("validate")
def contract_validate_command() -> None:
    """Validate editable Curator role contracts without mutating files."""
    result = validate_role_contracts(build_curator_paths(Path.cwd()))
    typer.echo(render_contract_validation_report(result))
    if not result.valid:
        raise typer.Exit(1)


@provider_app.command("add")
def provider_add_command(
    name: str = typer.Argument(..., help="Provider to add: claude-code or codex."),
) -> None:
    """Detect a provider CLI and store a provider profile for it."""
    _echo_init_write_summary(Path.cwd())
    connection = connect_database(build_curator_paths(Path.cwd()).database)
    try:
        initialize_database(connection)
        result = add_provider_profile(connection, name)
    finally:
        connection.close()
    typer.echo(result.message)
    if not result.created:
        raise typer.Exit(1)
    assert result.profile is not None
    typer.echo("Next: bind a slot with /agent bind writer.default " + result.profile.id)


@provider_app.command("list")
def provider_list_command() -> None:
    """List configured provider profiles."""
    paths = build_curator_paths(Path.cwd())
    if not paths.database.exists():
        typer.echo("Providers:\n- none (run curator provider add <name>)")
        return
    connection = connect_database(paths.database)
    try:
        initialize_database(connection)
        profiles = load_provider_profiles(connection)
    finally:
        connection.close()
    if not profiles:
        typer.echo("Providers:\n- none (run curator provider add <name>)")
        return
    typer.echo("Providers:")
    for profile in profiles:
        typer.echo(f"- {profile.id} {profile.provider.value} [{profile.status.value}]")

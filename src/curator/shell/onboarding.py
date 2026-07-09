"""Guide first-run setup and mode-aware shell entry."""

from pathlib import Path

from curator.core.paths import build_curator_paths
from curator.providers.detect import detect_available_providers, provider_setup_hint
from curator.providers.profiles import RuntimeMode, resolve_runtime_mode
from curator.state.db import connect_database, initialize_database


def first_run_needed(project_root: Path | str) -> bool:
    """Return whether this project has no Curator database yet."""
    return not build_curator_paths(project_root).database.exists()


def apply_first_run_init(project_root: Path | str) -> str:
    """Create Curator state for a fresh project and return a summary line.

    Imported lazily inside the function to avoid a shell/app import cycle.
    """
    from curator.app import write_init_state

    summary = write_init_state(project_root)
    detected = detect_available_providers(project_root)
    lines = [
        "Initialized Curator state for this project.",
        f"Created files: {summary.created_files_count}",
    ]
    if detected:
        names = ", ".join(provider.value for provider in detected)
        lines.append(f"Detected provider CLIs: {names}")
        lines.append(f"Next: {provider_setup_hint()}")
    else:
        lines.append("Next: install Claude Code or Codex, then run /provider add <name>.")
    return "\n".join(lines)


def resolve_mode_for_project(project_root: Path | str) -> RuntimeMode:
    """Return the effective execution mode for one project root."""
    paths = build_curator_paths(project_root)
    if not paths.database.exists():
        return RuntimeMode(label="setup", detail="project not initialized")

    connection = connect_database(paths.database)
    try:
        initialize_database(connection)
        return resolve_runtime_mode(connection)
    finally:
        connection.close()


def _next_action(project_root: Path | str, mode: RuntimeMode) -> str:
    """Return the single most useful next action for the welcome banner."""
    if first_run_needed(project_root):
        return "/init (or curator init) to set up this project"
    if mode.label == "setup":
        return provider_setup_hint()
    return "Type what you want to work on."


def build_welcome_text(project_root: Path | str) -> str:
    """Return the mode-aware interactive shell welcome text."""
    mode = resolve_mode_for_project(project_root)
    detected = detect_available_providers(project_root)
    detail = mode.detail
    if mode.label == "setup" and detected:
        names = ", ".join(provider.value for provider in detected)
        detail = f"{mode.detail}; detected CLIs: {names}"
    return "\n".join(
        [
            f"Curator — {Path(project_root).name}",
            f"Mode: {mode.label} ({detail})",
            f"Next: {_next_action(project_root, mode)}",
            "Type what you want to work on, or /help.",
        ]
    )

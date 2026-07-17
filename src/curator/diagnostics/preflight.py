"""Run startup environment checks before the shell accepts work."""

import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from curator.core.paths import build_curator_paths
from curator.harness.verifier import discover_verification_commands
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import load_latest_pause_record

_MIN_PYTHON = (3, 11)
_PROVIDER_BINARIES: dict[str, str] = {"claude-code": "claude", "codex": "codex"}
_STATUS_MARKS = {"ok": "✓", "warn": "!", "fail": "✗"}


@dataclass(frozen=True)
class PreflightCheck:
    """Describe one environment check outcome."""

    key: str
    status: str  # ok | warn | fail
    detail: str
    fix: str | None = None


@dataclass(frozen=True)
class PreflightReport:
    """Describe all startup environment checks for one project."""

    checks: tuple[PreflightCheck, ...]

    def get(self, key: str) -> PreflightCheck | None:
        """Return one check by key, or None when it was not run."""
        for check in self.checks:
            if check.key == key:
                return check
        return None


def _python_check() -> PreflightCheck:
    """Check the running interpreter against the supported floor."""
    version = sys.version.split()[0]
    floor = ".".join(str(part) for part in _MIN_PYTHON)
    if sys.version_info >= _MIN_PYTHON:
        return PreflightCheck(
            key="python", status="ok", detail=f"Python {version} (>= {floor} required)"
        )
    return PreflightCheck(
        key="python",
        status="fail",
        detail=f"Python {version} is below the required {floor}",
        fix=f"Install Python {floor}+ and reinstall curator.",
    )


def _git_check(project_root: Path) -> PreflightCheck:
    """Check repository presence and worktree cleanliness."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return PreflightCheck(
            key="git",
            status="warn",
            detail="git is not available — workspace safety checks are skipped",
        )
    if result.returncode != 0:
        return PreflightCheck(
            key="git",
            status="warn",
            detail="not a git repository — workspace safety checks are skipped",
        )
    changes = [line for line in result.stdout.splitlines() if line.strip()]
    if changes:
        noun = "change" if len(changes) == 1 else "changes"
        return PreflightCheck(
            key="git",
            status="warn",
            detail=(
                f"{len(changes)} uncommitted {noun} — real runs pause "
                "until the tree is clean"
            ),
            fix="Commit or stash your changes before starting a loop.",
        )
    return PreflightCheck(key="git", status="ok", detail="git working tree clean")


def _macos_keychain_has(service: str) -> bool:
    """Return whether the macOS keychain holds a credential for `service`.

    Read-only existence check (no `-w`), so it never decrypts the secret
    or triggers a keychain access prompt. A no-op off macOS.
    """
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _auth_state(provider_key: str) -> tuple[bool, str]:
    """Return (authenticated, detail) from local credential heuristics."""
    home = Path.home()
    if provider_key == "claude-code":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True, "logged in (API key in environment)"
        if (home / ".claude" / ".credentials.json").exists():
            return True, "logged in"
        # Claude Code stores its OAuth token in the macOS keychain rather
        # than a plaintext credentials file, so check there before warning.
        if _macos_keychain_has("Claude Code-credentials"):
            return True, "logged in (keychain)"
        return False, "login state unknown"
    if os.environ.get("OPENAI_API_KEY"):
        return True, "logged in (API key in environment)"
    if (home / ".codex" / "auth.json").exists():
        return True, "logged in"
    return False, "login state unknown"


def _login_fix(provider_key: str, binary: str) -> str:
    """Return the login guidance for one provider CLI."""
    if provider_key == "claude-code":
        return f"Run `{binary}` once in your terminal and sign in."
    return f"Run `{binary} login` in your terminal."


def _probe_provider(provider_key: str, binary: str) -> PreflightCheck:
    """Check one provider CLI for presence, version, and login state."""
    key = f"provider:{provider_key}"
    if shutil.which(binary) is None:
        return PreflightCheck(
            key=key,
            status="fail",
            detail=f"{binary} — not found on PATH",
            fix=f"Install the {provider_key} CLI ({binary}), then relaunch curator.",
        )
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return PreflightCheck(
            key=key,
            status="fail",
            detail=f"{binary} — failed to run --version",
            fix=f"Reinstall the {provider_key} CLI ({binary}).",
        )
    stdout = result.stdout.strip()
    version = stdout.splitlines()[0] if stdout else binary
    if not version.lower().startswith(binary):
        version = f"{binary} {version}"
    authed, auth_detail = _auth_state(provider_key)
    return PreflightCheck(
        key=key,
        status="ok" if authed else "warn",
        detail=f"{version} · {auth_detail}",
        fix=None if authed else _login_fix(provider_key, binary),
    )


def probe_provider(provider_key: str) -> PreflightCheck:
    """Probe one provider CLI by key (claude-code or codex)."""
    return _probe_provider(provider_key, _PROVIDER_BINARIES[provider_key])


def provider_auth_state(provider_key: str) -> tuple[bool, str]:
    """Return (authenticated, detail) for one provider key."""
    return _auth_state(provider_key)


def _verification_check(project_root: Path) -> PreflightCheck:
    """Check whether the VALIDATE step will find verification commands."""
    commands = discover_verification_commands(project_root)
    if not commands:
        return PreflightCheck(
            key="verification",
            status="warn",
            detail="no verification commands found — the VALIDATE step will pause",
            fix="Add tests (pytest) or a package.json test script.",
        )
    names = ", ".join(_command_display(command) for command in commands)
    return PreflightCheck(
        key="verification", status="ok", detail=f"verification commands: {names}"
    )


def _command_display(command: list[str]) -> str:
    """Return a short human name for one verification command."""
    if len(command) >= 3 and command[0] == sys.executable and command[1] == "-m":
        return " ".join(command[2:])
    return " ".join(command)


def _pause_check(project_root: Path) -> PreflightCheck | None:
    """Check for an open pause persisted from an earlier session."""
    database = build_curator_paths(project_root).database
    if not database.exists():
        return None
    try:
        connection = connect_database(database)
        try:
            initialize_database(connection)
            pause = load_latest_pause_record(connection)
        finally:
            connection.close()
    except Exception:  # noqa: BLE001 — a broken ledger must not block startup
        return None
    if pause is None:
        return None
    return PreflightCheck(
        key="pause",
        status="warn",
        detail=f"a paused loop is waiting: {pause.question}",
        fix="/resume <answer> · /revise <new scope> · /cancel",
    )


def run_preflight(project_root: Path | str) -> PreflightReport:
    """Run all startup checks and return the ordered report."""
    root = Path(project_root)
    with ThreadPoolExecutor(max_workers=len(_PROVIDER_BINARIES)) as executor:
        provider_futures = [
            executor.submit(_probe_provider, provider_key, binary)
            for provider_key, binary in _PROVIDER_BINARIES.items()
        ]
        checks: list[PreflightCheck] = [_python_check(), _git_check(root)]
        checks.extend(future.result() for future in provider_futures)
    checks.append(_verification_check(root))
    pause = _pause_check(root)
    if pause is not None:
        checks.append(pause)
    return PreflightReport(checks=tuple(checks))


def run_preflight_streaming(
    project_root: Path | str,
    on_check: Callable[[PreflightCheck], None],
) -> PreflightReport:
    """Run startup checks and emit each completed check to a UI callback."""
    report = run_preflight(project_root)
    for check in report.checks:
        on_check(check)
    return report


def render_preflight(report: PreflightReport) -> str:
    """Render the preflight report as terminal-friendly text."""
    lines = ["Preflight:"]
    for check in report.checks:
        mark = _STATUS_MARKS.get(check.status, "?")
        lines.append(f"  {mark} {check.detail}")
        if check.fix is not None:
            lines.append(f"      fix: {check.fix}")
    return "\n".join(lines)

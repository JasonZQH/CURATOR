"""Verify the product banner and startup environment preflight."""

import os
import subprocess
import sys

from curator.app import start_goal_loop
from curator.core.paths import build_curator_paths
from curator.diagnostics.preflight import render_preflight, run_preflight
from curator.goals.store import accept_goal, propose_goal, save_goal
from curator.shell.banner import git_branch, render_banner
from fakes import enable_live_mode, install_fake_claude


def _fake_provider_bin(tmp_path, names=("claude", "codex")) -> str:
    """Create fake provider binaries and return a PATH covering them."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        script = bin_dir / name
        script.write_text(
            "#!/usr/bin/env python3\n"
            f'print("{name} 9.9.9 (fake)")\n'
        )
        script.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"


def _git_repo(tmp_path) -> None:
    """Initialize a git repository with one commit in tmp_path."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )


def test_render_banner_shows_identity_line(tmp_path):
    """Verify the banner carries version, project path, and ASCII art."""
    banner = render_banner(tmp_path)

    assert "____" in banner
    assert "curator v0.1.0" in banner
    assert tmp_path.name in banner


def test_render_banner_includes_git_branch(tmp_path):
    """Verify the identity line names the current git branch."""
    _git_repo(tmp_path)

    assert git_branch(tmp_path) == "main"
    assert "git:main" in render_banner(tmp_path)


def test_git_branch_is_none_outside_repositories(tmp_path):
    """Verify non-git directories produce no branch segment."""
    assert git_branch(tmp_path) is None
    assert "git:" not in render_banner(tmp_path)


def test_preflight_python_check_passes_on_supported_interpreter(tmp_path):
    """Verify the python check reflects the running interpreter."""
    report = run_preflight(tmp_path)

    check = report.get("python")
    assert check.status == "ok"
    assert sys.version.split()[0] in check.detail


def test_preflight_warns_outside_git_repositories(tmp_path):
    """Verify a non-git project warns that safety checks are skipped."""
    report = run_preflight(tmp_path)

    check = report.get("git")
    assert check.status == "warn"
    assert "not a git repository" in check.detail


def test_preflight_flags_dirty_worktree_before_runs_do(tmp_path):
    """Verify uncommitted changes are surfaced at startup, not mid-run."""
    _git_repo(tmp_path)
    (tmp_path / "dirty.txt").write_text("x\n")

    check = run_preflight(tmp_path).get("git")

    assert check.status == "warn"
    assert "uncommitted" in check.detail
    assert check.fix is not None


def test_preflight_reports_clean_git_worktree(tmp_path):
    """Verify a clean repository passes the git check."""
    _git_repo(tmp_path)

    check = run_preflight(tmp_path).get("git")

    assert check.status == "ok"
    assert "clean" in check.detail


def test_preflight_detects_provider_clis_with_versions(tmp_path, monkeypatch):
    """Verify provider checks report detected versions from PATH."""
    monkeypatch.setenv("PATH", _fake_provider_bin(tmp_path))

    report = run_preflight(tmp_path)

    claude = report.get("provider:claude-code")
    codex = report.get("provider:codex")
    assert "9.9.9" in claude.detail
    assert "9.9.9" in codex.detail
    assert claude.status in {"ok", "warn"}


def test_preflight_fails_missing_provider_clis_with_fix(tmp_path, monkeypatch):
    """Verify absent provider binaries fail with install guidance."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}{os.pathsep}/usr/bin{os.pathsep}/bin")

    report = run_preflight(tmp_path)

    check = report.get("provider:claude-code")
    assert check.status == "fail"
    assert "not found" in check.detail
    assert check.fix is not None


def test_preflight_reports_claude_login_from_credentials_file(tmp_path, monkeypatch):
    """Verify the claude auth heuristic reads the credentials file."""
    monkeypatch.setenv("PATH", _fake_provider_bin(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))

    check = run_preflight(tmp_path).get("provider:claude-code")

    assert check.status == "ok"
    assert "logged in" in check.detail


def test_preflight_marks_unknown_login_state_as_warning(tmp_path, monkeypatch):
    """Verify missing credential markers degrade to a warning, not a failure."""
    monkeypatch.setenv("PATH", _fake_provider_bin(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    check = run_preflight(tmp_path).get("provider:claude-code")

    assert check.status == "warn"
    assert "login" in check.detail


def test_preflight_warns_when_no_verification_commands_exist(tmp_path):
    """Verify a testless project is warned about the VALIDATE pause."""
    check = run_preflight(tmp_path).get("verification")

    assert check.status == "warn"
    assert "VALIDATE" in check.detail


def test_preflight_lists_discovered_verification_commands(tmp_path):
    """Verify detected test commands are named in the check detail."""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (tmp_path / "tests").mkdir()

    check = run_preflight(tmp_path).get("verification")

    assert check.status == "ok"
    assert "pytest" in check.detail


def test_preflight_surfaces_open_pause_records(tmp_path, monkeypatch):
    """Verify a persisted open pause is visible before the first prompt."""
    enable_live_mode(tmp_path)
    install_fake_claude(tmp_path, monkeypatch)
    paths = build_curator_paths(tmp_path)
    goal = propose_goal("Fix mobile login layout")
    save_goal(paths, goal)
    revision_id = accept_goal(paths, goal.id).revision_id
    start_goal_loop(tmp_path, revision_id)

    check = run_preflight(tmp_path).get("pause")

    assert check.status == "warn"
    assert "/resume" in check.fix


def test_preflight_omits_pause_check_without_state(tmp_path):
    """Verify fresh projects carry no pause noise."""
    assert run_preflight(tmp_path).get("pause") is None


def test_render_preflight_marks_status_per_line(tmp_path, monkeypatch):
    """Verify the rendered preflight uses distinct ok/warn/fail marks."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}{os.pathsep}/usr/bin{os.pathsep}/bin")

    text = render_preflight(run_preflight(tmp_path))

    assert "Preflight:" in text
    assert "✓" in text
    assert "!" in text
    assert "✗" in text
    assert "fix:" in text

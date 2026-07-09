"""Capture real workspace evidence from git for provider runs.

Real providers edit files in the project directory; Curator records what
changed by diffing the git working tree against a clean baseline captured
before dispatch.
"""

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceBaseline:
    """Describe the git state observed before a writer run."""

    is_git_repo: bool
    head: str | None
    clean: bool
    status_entries: list[str] = field(default_factory=list)


class WorkspaceDirtyError(RuntimeError):
    """Signal that a provider writer run would overwrite user-owned changes."""


@dataclass(frozen=True)
class WorkspaceEvidence:
    """Describe the file changes observed after a writer run."""

    changed_files: list[str] = field(default_factory=list)
    diff_text: str = ""
    content_hash: str | None = None
    diff_path: Path | None = None


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command inside the project workspace."""
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _is_git_repo(project_root: Path) -> bool:
    """Return whether the project root is inside a git work tree."""
    result = _git(project_root, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _porcelain_path(line: str) -> str:
    """Return the file path from one `git status --porcelain` line."""
    # Format: "XY <path>", with renames written "XY old -> new".
    path = line[3:].strip() if len(line) > 3 else line.strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"')


def _is_curator_state(path: str) -> bool:
    """Return whether a status path is Curator's own local state directory."""
    return path == ".curator" or path.startswith(".curator/")


def capture_baseline(project_root: Path | str) -> WorkspaceBaseline:
    """Record the git HEAD and cleanliness before a writer run.

    Curator's own `.curator/` state directory is excluded from the cleanliness
    check so the tool never blocks a writer on the state it just created.
    """
    root = Path(project_root)
    if not _is_git_repo(root):
        return WorkspaceBaseline(is_git_repo=False, head=None, clean=True)

    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    entries = [
        line
        for line in status.stdout.splitlines()
        if line.strip() and not _is_curator_state(_porcelain_path(line))
    ]
    return WorkspaceBaseline(
        is_git_repo=True,
        head=head.stdout.strip() or None,
        clean=not entries,
        status_entries=entries,
    )


def require_clean_baseline(baseline: WorkspaceBaseline) -> None:
    """Raise when a git workspace already had changes before provider dispatch."""
    if baseline.is_git_repo and not baseline.clean:
        preview = ", ".join(baseline.status_entries[:5])
        if len(baseline.status_entries) > 5:
            preview = f"{preview}, ..."
        raise WorkspaceDirtyError(
            "Workspace has uncommitted changes before provider run"
            + (f": {preview}" if preview else ".")
        )


def _untracked_files(root: Path) -> list[str]:
    """Return untracked files that are not ignored by git."""
    result = _git(root, "ls-files", "--others", "--exclude-standard")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _untracked_manifest(root: Path, files: list[str]) -> str:
    """Return a bounded text manifest for untracked files created by a provider."""
    if not files:
        return ""
    lines = ["", "Untracked files:"]
    for name in files:
        path = root / name
        size = path.stat().st_size if path.exists() and path.is_file() else 0
        lines.append(f"- {name} ({size} bytes)")
    return "\n".join(lines) + "\n"


def capture_workspace_evidence(
    project_root: Path | str,
    baseline: WorkspaceBaseline,
    loop_run_id: str,
    iteration_id: str,
) -> WorkspaceEvidence:
    """Diff the workspace against the baseline and persist the diff artifact."""
    root = Path(project_root)
    if not baseline.is_git_repo:
        return WorkspaceEvidence()

    name_status = _git(root, "diff", "--name-only", "HEAD")
    tracked_changed = [line for line in name_status.stdout.splitlines() if line.strip()]
    untracked = _untracked_files(root)
    changed = [*tracked_changed, *untracked]
    diff = _git(root, "diff", "HEAD")
    diff_text = diff.stdout + _untracked_manifest(root, untracked)
    if not diff_text:
        return WorkspaceEvidence(changed_files=changed)

    diff_bytes = diff_text.encode("utf-8")
    artifact_dir = root / ".curator" / "artifacts" / loop_run_id / iteration_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    diff_path = artifact_dir / "implementation.diff"
    diff_path.write_bytes(diff_bytes)
    digest = hashlib.sha256(diff_bytes).hexdigest()

    return WorkspaceEvidence(
        changed_files=changed,
        diff_text=diff_text,
        content_hash=f"sha256:{digest}",
        diff_path=diff_path,
    )

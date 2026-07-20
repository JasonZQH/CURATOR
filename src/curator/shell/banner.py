"""Render the Curator product banner for shell startup."""

from pathlib import Path

from curator import __version__

ASCII_BANNER = r"""
  _____ _    _ _____         _______ ____  _____
 / ____| |  | |  __ \     /\|__   __/ __ \|  __ \
| |    | |  | | |__) |   /  \  | | | |  | | |__) |
| |    | |  | |  _  /   / /\ \ | | | |  | |  _  /
| |____| |__| | | \ \  / ____ \| | | |__| | | \ \
 \_____|\____/|_|  \_\/_/    \_\_|  \____/|_|  \_\
""".strip("\n")

SLOGAN = "Plan with confidence. Ship with evidence."

WHATS_NEW = (
    "Full-screen first-run trust and setup",
    "Keyboard-selectable slash commands and proposal actions",
    "PM (main deck), Engineer, and Reviewer seat labels",
    "Persistent history, Tab completion, and Shift+Enter continuation",
)


def git_branch(project_root: Path | str) -> str | None:
    """Return the checked-out branch name, or None outside a repository."""
    git_path = Path(project_root) / ".git"
    head_file = git_path / "HEAD"
    if git_path.is_file():
        # Worktree checkouts store a pointer file instead of a directory.
        content = git_path.read_text().strip()
        if not content.startswith("gitdir:"):
            return None
        head_file = Path(content.removeprefix("gitdir:").strip()) / "HEAD"
    if not head_file.exists():
        return None

    head = head_file.read_text().strip()
    if head.startswith("ref: refs/heads/"):
        return head.removeprefix("ref: refs/heads/")
    return head[:7] or None


def render_banner(project_root: Path | str) -> str:
    """Return the ASCII banner with the version/path/branch identity line."""
    root = Path(project_root)
    identity = f"curator v{__version__} · {root}"
    branch = git_branch(root)
    if branch is not None:
        identity = f"{identity} · git:{branch}"
    return f"{ASCII_BANNER}\n\n  {identity}"

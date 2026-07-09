"""Render the Curator product banner for shell startup."""

from pathlib import Path

from curator import __version__

ASCII_BANNER = r"""
  ____ _   _ ____      _  _____ ___  ____
 / ___| | | |  _ \    / \|_   _/ _ \|  _ \
| |   | | | | |_) |  / _ \ | || | | | |_) |
| |___| |_| |  _ <  / ___ \| || |_| |  _ <
 \____|\___/|_| \_\/_/   \_\_| \___/|_| \_\
""".strip("\n")


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

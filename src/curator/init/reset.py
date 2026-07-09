"""Reset project-local Curator state safely."""

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from curator.core.paths import build_curator_paths
from curator.core.schema import CuratorPaths


@dataclass(frozen=True)
class ResetSummary:
    """Describe the filesystem effects of one reset run."""

    hard: bool
    archived_database: Path | None = None
    removed_paths: list[Path] = field(default_factory=list)
    preserved_paths: list[Path] = field(default_factory=list)


def _reset_targets(paths: CuratorPaths) -> list[Path]:
    """Return the state directories a soft reset removes."""
    return [
        paths.goals_dir,
        paths.sessions_dir,
        paths.worktrees_dir,
        paths.logs_dir,
    ]


def _preserved_targets(paths: CuratorPaths) -> list[Path]:
    """Return the user-edited directories a soft reset keeps."""
    return [paths.team_dir, paths.memory_dir]


def build_reset_summary(project_root: Path | str, hard: bool = False) -> ResetSummary:
    """Describe what a reset would touch without changing files."""
    paths = build_curator_paths(project_root)
    if hard:
        return ResetSummary(
            hard=True,
            removed_paths=[paths.curator_dir] if paths.curator_dir.exists() else [],
        )

    return ResetSummary(
        hard=False,
        archived_database=paths.database if paths.database.exists() else None,
        removed_paths=[target for target in _reset_targets(paths) if target.exists()],
        preserved_paths=[target for target in _preserved_targets(paths) if target.exists()],
    )


def reset_curator_state(
    project_root: Path | str,
    hard: bool = False,
    now: datetime | None = None,
) -> ResetSummary:
    """Reset Curator state, archiving the ledger unless a hard reset is asked."""
    paths = build_curator_paths(project_root)
    if hard:
        removed = []
        if paths.curator_dir.exists():
            shutil.rmtree(paths.curator_dir)
            removed.append(paths.curator_dir)
        return ResetSummary(hard=True, removed_paths=removed)

    archived_database = None
    if paths.database.exists():
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = paths.curator_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_database = archive_dir / f"curator-{stamp}.sqlite"
        shutil.move(str(paths.database), str(archived_database))

    removed_paths = []
    for target in _reset_targets(paths):
        if target.exists():
            shutil.rmtree(target)
            removed_paths.append(target)

    return ResetSummary(
        hard=False,
        archived_database=archived_database,
        removed_paths=removed_paths,
        preserved_paths=[target for target in _preserved_targets(paths) if target.exists()],
    )


def render_reset_summary(summary: ResetSummary, applied: bool) -> str:
    """Render one reset summary for terminal output."""
    verb_removed = "Removed" if applied else "Will remove"
    verb_archived = "Archived ledger to" if applied else "Will archive ledger to"
    lines = ["Curator reset (hard)" if summary.hard else "Curator reset"]
    if summary.archived_database is not None:
        lines.append(f"{verb_archived}: {summary.archived_database}")
    if summary.removed_paths:
        lines.append(f"{verb_removed}:")
        lines.extend(f"- {path}" for path in summary.removed_paths)
    else:
        lines.append(f"{verb_removed}: nothing")
    if summary.preserved_paths:
        lines.append("Preserved (user-edited):")
        lines.extend(f"- {path}" for path in summary.preserved_paths)
    return "\n".join(lines)

"""Detect a provider editing the control plane's own governance files.

`.curator/` sits inside the one writable root a provider is given, and it is invisible to
every diff-based check: the repository gitignores it, `curator init` writes
`.curator/.gitignore` containing `*`, and `harness/workspace.py` filters it out of git
porcelain. So an agent that rewrites its own role contract leaves no trace in the evidence
a step produces.

Claude Code can be told to refuse those paths at the argv layer, but `codex exec` has no
deny mechanism for a subpath of its workspace-write root — the only provider-agnostic
control available before workspaces are isolated (v0.1.6) is to hash the governance files
around a dispatch and refuse the step's evidence if they moved.

Scope, stated plainly: this covers the contract and role documents under `.curator/team`.
It deliberately does NOT cover `curator.sqlite`, because Curator writes the ledger
throughout a step — iterations, events, provider runs — so any before/after comparison of
it would fire on every run. Keeping the ledger out of a provider's reach is a workspace
boundary problem, not a checksum problem.
"""

import hashlib
from enum import Enum
from pathlib import Path

from curator.core.schema import CuratorPaths

# A file Curator could not read is reported as changed rather than skipped: an unreadable
# contract is exactly what tampering looks like, and silence would be the wrong default.
_UNREADABLE = "unreadable"


class GovernanceViolation(str, Enum):
    """Name the way governance state changed while a provider was running."""

    CHANGED = "governance_state_changed"
    ADDED = "governance_state_added"
    REMOVED = "governance_state_removed"

    @property
    def reason(self) -> str:
        """Return the pause reason shown to the user for this violation."""
        return _VIOLATION_REASONS[self]


_VIOLATION_REASONS = {
    GovernanceViolation.CHANGED: (
        "A provider changed Curator's own role contracts while it was running. The step's "
        "evidence was refused. Review the diff under .curator/team, restore it if you did "
        "not intend the change, then resume."
    ),
    GovernanceViolation.ADDED: (
        "A provider added a file to Curator's role contracts while it was running. The "
        "step's evidence was refused. Review .curator/team, remove what you did not intend, "
        "then resume."
    ),
    GovernanceViolation.REMOVED: (
        "A provider deleted one of Curator's role contracts while it was running. The "
        "step's evidence was refused. Restore .curator/team, then resume."
    ),
}


def _digest(path: Path) -> str:
    """Return a content digest for one governance file, or the unreadable sentinel."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return _UNREADABLE


def snapshot_governance(paths: CuratorPaths) -> dict[str, str]:
    """Return a content digest per governance file, keyed by path relative to the project.

    Reading follows symlinks on purpose: what matters is the bytes the control plane would
    load, so a contract pointed somewhere else is still compared by its resolved content.
    """
    if not paths.team_dir.is_dir():
        return {}

    snapshot: dict[str, str] = {}
    for entry in sorted(paths.team_dir.rglob("*")):
        if entry.is_dir():
            continue
        snapshot[str(entry.relative_to(paths.project_root))] = _digest(entry)
    return snapshot


def detect_governance_change(
    before: dict[str, str], after: dict[str, str]
) -> GovernanceViolation | None:
    """Return how governance state changed between two snapshots, or None if it held."""
    if before == after:
        return None
    if set(after) - set(before):
        return GovernanceViolation.ADDED
    if set(before) - set(after):
        return GovernanceViolation.REMOVED
    return GovernanceViolation.CHANGED

"""Project action policy into provider-native permission configuration.

Curator cannot intercept file or shell actions inside an out-of-process CLI, so
the action policy is expressed as each provider's own permission flags: the CLI
enforces them natively. Writer slots may edit the workspace; reviewer slots run
read-only so the single-writer principle holds across heterogeneous providers.
"""

from curator.runtime.action_policy import ActionPolicy

WRITER_SLOT = "writer"
REVIEWER_SLOT = "reviewer"

_CLAUDE_WRITER_TOOLS = "Edit Write Read Grep Glob Bash(uv run pytest*) Bash(git *)"
_CLAUDE_READER_TOOLS = "Read Grep Glob"
_CLAUDE_DISALLOWED = "Bash(git push*) WebFetch"


def _is_reviewer(slot: str | None) -> bool:
    """Return whether a slot must run without workspace writes."""
    return slot == REVIEWER_SLOT


def claude_permission_args(policy: ActionPolicy, slot: str | None) -> list[str]:
    """Return Claude Code CLI permission flags derived from the action policy."""
    args = ["--add-dir", str(policy.project_root)]
    if _is_reviewer(slot):
        return [*args, "--permission-mode", "plan", "--allowedTools", _CLAUDE_READER_TOOLS]
    return [
        *args,
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        _CLAUDE_WRITER_TOOLS,
        "--disallowedTools",
        _CLAUDE_DISALLOWED,
    ]


def codex_sandbox_args(policy: ActionPolicy, slot: str | None) -> list[str]:
    """Return Codex CLI sandbox flags derived from the action policy."""
    sandbox = "read-only" if _is_reviewer(slot) else "workspace-write"
    return [
        "--sandbox",
        sandbox,
        "--ask-for-approval",
        "never",
        "--cd",
        str(policy.project_root),
    ]

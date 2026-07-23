"""Project action policy into provider-native permission configuration.

Curator cannot intercept file or shell actions inside an out-of-process CLI, so
the action policy is expressed as each provider's own permission flags: the CLI
enforces them natively. Writer slots may edit the workspace; reviewer slots run
read-only so the single-writer principle holds across heterogeneous providers.
"""

from curator.runtime.action_policy import ActionPolicy

WRITER_SLOT = "writer"
REVIEWER_SLOT = "reviewer"
MAIN_DECK_SLOT = "maindeck"

# Claude Code's --allowedTools/--disallowedTools accept a comma- OR space-separated
# list. Tool specs like "Bash(git *)" contain a space, so the value MUST be
# comma-separated (each whole spec is passed as one argv element) or the space
# would split one spec into broken tokens.
_CLAUDE_WRITER_TOOLS = "Edit,Write,Read,Grep,Glob,Bash(uv run pytest*),Bash(git *)"
_CLAUDE_READER_TOOLS = "Read,Grep,Glob"
_CLAUDE_DISALLOWED = "Bash(git push*),WebFetch"


def _is_reviewer(slot: str | None) -> bool:
    """Return whether a slot must run without workspace writes."""
    return slot in {REVIEWER_SLOT, MAIN_DECK_SLOT}


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
    """Return Codex CLI sandbox flags derived from the action policy.

    `codex exec` is non-interactive and has no --ask-for-approval flag; the
    sandbox mode alone governs what model-generated commands may do. Writer
    slots get workspace-write; reviewer slots stay read-only.
    """
    sandbox = "read-only" if _is_reviewer(slot) else "workspace-write"
    return [
        "--sandbox",
        sandbox,
        "--cd",
        str(policy.project_root),
    ]

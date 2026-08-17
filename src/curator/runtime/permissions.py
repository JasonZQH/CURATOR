"""Project action policy into provider-native permission configuration.

Curator cannot intercept file or shell actions inside an out-of-process CLI, so
the action policy is expressed as each provider's own permission flags: the CLI
enforces them natively. Writer slots may edit the workspace; reviewer slots run
read-only so the single-writer principle holds across heterogeneous providers.
"""

from curator.runtime.action_policy import ActionPolicy

WRITER_SLOT = "writer"

# Claude Code's --allowedTools/--disallowedTools accept a comma- OR space-separated
# list. Tool specs like "Bash(git status*)" contain a space, so the value MUST be
# comma-separated (each whole spec is passed as one argv element) or the space
# would split one spec into broken tokens.
#
# The git verbs are enumerated rather than granted as `Bash(git *)`: that wildcard also
# handed the writer `git config`, `git checkout`, and `git worktree`, so it could rewrite
# the branch base that workspace isolation is going to depend on, and the `git push*`
# denial rested on prefix matching a command it could spell another way.
_CLAUDE_WRITER_TOOLS = (
    "Edit,Write,Read,Grep,Glob,Bash(uv run pytest*),"
    "Bash(git status*),Bash(git diff*),Bash(git add*),Bash(git log*)"
)
_CLAUDE_READER_TOOLS = "Read,Grep,Glob"
# Curator's own state is off limits to every seat. Claude can enforce this at the argv
# layer; codex exec has no equivalent, which is why runtime/governance.py checks after
# the fact for both.
_CLAUDE_DISALLOWED = (
    "Bash(git push*),WebFetch,"
    "Edit(.curator/**),Write(.curator/**),Read(.curator/**)"
)


def _is_writer(slot: str | None) -> bool:
    """Return whether a slot may write the workspace.

    An allowlist, not a denylist: an unknown slot — a typo, a slot added by a later
    version, or the None a step compiles with when it declares no slot at all — must land
    on read-only. Naming the reviewers instead meant everything else fell through to
    workspace-write, so the permissive branch was the default.
    """
    return slot == WRITER_SLOT


def claude_permission_args(policy: ActionPolicy, slot: str | None) -> list[str]:
    """Return Claude Code CLI permission flags derived from the action policy."""
    args = ["--add-dir", str(policy.project_root)]
    if not _is_writer(slot):
        return [
            *args,
            "--permission-mode",
            "plan",
            "--allowedTools",
            _CLAUDE_READER_TOOLS,
            "--disallowedTools",
            _CLAUDE_DISALLOWED,
        ]
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
    sandbox mode alone governs what model-generated commands may do. Only the writer
    slot gets workspace-write; everything else stays read-only.

    Note the asymmetry with Claude: codex has no way to deny a subpath of the root it can
    write, so `.curator` stays reachable to a codex writer until workspaces are isolated.
    runtime/governance.py is what catches that, after the fact, on both seats.
    """
    sandbox = "workspace-write" if _is_writer(slot) else "read-only"
    return [
        "--sandbox",
        sandbox,
        "--cd",
        str(policy.project_root),
    ]

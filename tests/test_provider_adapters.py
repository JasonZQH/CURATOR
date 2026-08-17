"""Verify Claude Code and Codex adapters, permissions, and profile wiring."""

import subprocess
from datetime import UTC, datetime

import pytest

from curator.core.enums import (
    EvidenceKind,
    LoopDecisionType,
    LoopStepType,
    ProviderName,
    ProviderProfileStatus,
    RoleName,
    StepExecutorType,
)
from curator.core.schema import CompiledLoopStep, EvidenceRef, HarnessRunSpec
from curator.context.packaging import ContextPackage
from curator.providers.claude_code import ClaudeCodeDriver
from curator.providers.codex_cli import CodexCliDriver
from curator.providers.contracts import ProviderRunRequest
from curator.providers.events import ProviderEventKind
from curator.providers.registry import ProviderConfigurationError, resolve_provider_for_step
from curator.providers.setup import add_provider_profile
from curator.runtime.action_policy import ActionPolicy
from curator.runtime.permissions import claude_permission_args, codex_sandbox_args
from curator.runtime.role_pool import ensure_default_role_pool
from curator.harness.workspace import (
    WorkspaceDirtyError,
    capture_baseline,
    capture_workspace_evidence,
    require_clean_baseline,
)
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_role_provider_binding,
    load_provider_profiles,
)


def _spec(step_type: LoopStepType, role: RoleName) -> HarnessRunSpec:
    """Build a minimal harness spec for adapter tests."""
    return HarnessRunSpec(
        id="harness-001",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-001",
        role=role,
        step_type=step_type,
        task_id="task-001",
    )


def _request(spec: HarnessRunSpec) -> ProviderRunRequest:
    """Build a provider run request from a spec."""
    return ProviderRunRequest.from_harness_spec(spec)


def _allowed_tools(args: list[str]) -> list[str]:
    """Return the tool specs a permission argv grants."""
    return args[args.index("--allowedTools") + 1].split(",")


def test_claude_permission_args_differ_by_slot(tmp_path):
    """Verify writer slots can edit while reviewer slots stay read-only."""
    policy = ActionPolicy.for_project(tmp_path)
    writer = claude_permission_args(policy, "writer")
    reviewer = claude_permission_args(policy, "reviewer")

    assert "acceptEdits" in writer
    assert "Write" in _allowed_tools(writer)
    assert "plan" in reviewer
    assert "Write" not in _allowed_tools(reviewer)


def test_claude_permission_args_deny_an_unknown_slot(tmp_path):
    """Verify a slot that is not the writer gets read-only, whatever it is called.

    The check used to name the read-only slots, so anything unrecognised — a typo, a slot
    added later, or the None a step compiles with when it declares no slot — fell through
    to the workspace-write branch. The permissive branch must not be the default.
    """
    policy = ActionPolicy.for_project(tmp_path)

    for slot in (None, "", "Writer", "reviewer", "security-auditor"):
        args = claude_permission_args(policy, slot)
        assert "plan" in args, slot
        assert "acceptEdits" not in args, slot
        assert "Write" not in _allowed_tools(args), slot
        assert codex_sandbox_args(policy, slot).count("read-only") == 1, slot


def test_claude_permission_args_deny_curator_state(tmp_path):
    """Verify no seat is allowed to touch Curator's own state through the Claude CLI."""
    policy = ActionPolicy.for_project(tmp_path)

    for slot in ("writer", "reviewer", None):
        args = claude_permission_args(policy, slot)
        denied = args[args.index("--disallowedTools") + 1].split(",")
        assert "Write(.curator/**)" in denied, slot
        assert "Edit(.curator/**)" in denied, slot


def test_claude_writer_cannot_run_arbitrary_git_subcommands(tmp_path):
    """Verify the writer gets named git verbs, not the whole command.

    `Bash(git *)` also granted `git config`, `git checkout`, and `git worktree` — enough to
    rewrite the branch base workspace isolation depends on — and left the `git push*`
    denial resting on prefix matching alone.
    """
    policy = ActionPolicy.for_project(tmp_path)
    allowed = _allowed_tools(claude_permission_args(policy, "writer"))

    assert "Bash(git *)" not in allowed
    assert "Bash(git status*)" in allowed
    assert not any(spec.startswith("Bash(git config") for spec in allowed)


def test_claude_tool_lists_are_comma_separated_single_args(tmp_path):
    """Verify tool specs with spaces stay intact as one comma-separated argv value.

    Claude's --allowedTools splits on spaces, so "Bash(git status*)" must ride inside a
    single comma-separated argument, never split across argv elements.
    """
    policy = ActionPolicy.for_project(tmp_path)
    writer = claude_permission_args(policy, "writer")
    tools_value = writer[writer.index("--allowedTools") + 1]

    assert "," in tools_value
    assert "Bash(git status*)" in tools_value.split(",")
    # The spec must never appear as its own broken argv token.
    assert "Bash(git" not in writer
    assert "status*)" not in writer


def test_codex_sandbox_args_differ_by_slot(tmp_path):
    """Verify writer slots get workspace-write and reviewers read-only."""
    policy = ActionPolicy.for_project(tmp_path)
    writer = codex_sandbox_args(policy, "writer")
    reviewer = codex_sandbox_args(policy, "reviewer")
    assert "workspace-write" in writer
    assert "read-only" in reviewer
    # `codex exec` 0.143.0 has no --ask-for-approval flag; it must not be emitted.
    assert "--ask-for-approval" not in writer
    assert "--ask-for-approval" not in reviewer


def test_claude_driver_build_argv_includes_stream_json(tmp_path):
    """Verify the Claude adapter requests stream-json output."""
    driver = ClaudeCodeDriver(tmp_path, slot="writer")
    spec = _spec(LoopStepType.IMPLEMENT, RoleName.ENGINEER)
    argv = driver.build_argv(spec, _request(spec))

    assert argv[0] == "claude"
    assert "--output-format" in argv
    assert "stream-json" in argv
    # --max-turns is not a valid Claude Code flag; it must not be emitted.
    assert "--max-turns" not in argv


def test_context_package_request_reaches_cli_prompts(tmp_path):
    """Verify context package goal, memory, constraints, and evidence reach CLI prompts."""
    spec = _spec(LoopStepType.IMPLEMENT, RoleName.ENGINEER).model_copy(
        update={
            "context_refs": [
                EvidenceRef(
                    id="evidence-001",
                    session_id="session-001",
                    loop_run_id="loop-run-001",
                    iteration_id="iteration-001",
                    kind=EvidenceKind.IMPLEMENTATION,
                    uri="provider-output://implementation",
                    summary="Previous implementation changed login.css.",
                    producer_role=RoleName.ENGINEER,
                    created_at=datetime(2026, 7, 8, tzinfo=UTC),
                )
            ]
        }
    )
    package = ContextPackage(
        id="context-001",
        session_id=spec.session_id,
        loop_run_id=spec.loop_run_id,
        iteration_id=spec.iteration_id,
        role=spec.role,
        task_id=spec.task_id,
        project_root=str(tmp_path),
        goal_snapshot={"summary": "Fix mobile login layout"},
        memory_summaries=["Keep auth flow unchanged."],
        repo_state_summary="Project root only.",
        constraints=["Do not change auth flow."],
        allowed_actions=["read_file", "write_file"],
        disallowed_actions=["destructive_shell"],
    )
    request = ProviderRunRequest.from_context_package(spec, package)

    claude_driver = ClaudeCodeDriver(tmp_path, slot="writer")
    codex_driver = CodexCliDriver(tmp_path, slot="writer")
    assert "Fix mobile login layout" not in " ".join(claude_driver.build_argv(spec, request))
    assert "Fix mobile login layout" not in " ".join(codex_driver.build_argv(spec, request))
    claude_prompt = claude_driver.build_prompt(spec, request)
    codex_prompt = codex_driver.build_prompt(spec, request)

    for prompt in (claude_prompt, codex_prompt):
        assert "Fix mobile login layout" in prompt
        assert "Do not change auth flow." in prompt
        assert "Previous implementation changed login.css." in prompt
        assert "Keep auth flow unchanged." in prompt


def test_claude_driver_parses_stream_json_events(tmp_path):
    """Verify Claude stream-json lines map to tool-call and usage events."""
    driver = ClaudeCodeDriver(tmp_path, slot="writer")
    tool_line = (
        '{"type": "assistant", "message": {"content": '
        '[{"type": "tool_use", "name": "Edit"}]}}'
    )
    result_line = '{"type": "result", "subtype": "success", "result": "Edited foo.py."}'

    tool_event = driver.parse_event(tool_line, "harness-001", 1)
    usage_event = driver.parse_event(result_line, "harness-001", 2)

    assert tool_event is not None
    assert tool_event.kind is ProviderEventKind.TOOL_CALL
    assert tool_event.label == "Edit"
    assert usage_event is not None
    assert usage_event.kind is ProviderEventKind.USAGE
    assert driver._final_text["harness-001"] == "Edited foo.py."


def test_claude_driver_tolerates_malformed_lines(tmp_path):
    """Verify malformed JSONL lines are dropped, not fatal."""
    driver = ClaudeCodeDriver(tmp_path, slot="writer")
    assert driver.parse_event("not json", "harness-001", 1) is None
    assert driver.parse_event("", "harness-001", 2) is None


def test_codex_driver_parses_item_events(tmp_path):
    """Verify Codex item events map to tool-call and output events."""
    driver = CodexCliDriver(tmp_path, slot="writer")
    command_line = '{"type": "item.completed", "item": {"type": "command_execution"}}'
    message_line = '{"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}'

    command_event = driver.parse_event(command_line, "harness-001", 1)
    message_event = driver.parse_event(message_line, "harness-001", 2)

    assert command_event is not None
    assert command_event.kind is ProviderEventKind.TOOL_CALL
    assert message_event is not None
    assert message_event.kind is ProviderEventKind.OUTPUT_CHUNK
    assert driver._final_text["harness-001"] == "done"


def test_codex_tool_call_carries_the_item_id_shared_by_its_lifecycle(tmp_path):
    """Verify both lifecycle events of one command carry the same id, so it counts once.

    Line shapes are copied from a real `codex exec --json` run.
    """
    driver = CodexCliDriver(tmp_path, slot="writer")
    started = (
        '{"type":"item.started","item":{"id":"item_1","type":"command_execution",'
        '"command":"/bin/zsh -lc \'echo ok\'","exit_code":null,"status":"in_progress"}}'
    )
    completed = (
        '{"type":"item.completed","item":{"id":"item_1","type":"command_execution",'
        '"command":"/bin/zsh -lc \'echo ok\'","exit_code":0,"status":"completed"}}'
    )

    events = [driver.parse_event(line, "harness-001", i) for i, line in enumerate((started, completed))]

    assert [event.kind for event in events] == [ProviderEventKind.TOOL_CALL] * 2
    assert {event.payload["item_id"] for event in events} == {"item_1"}


def test_codex_tool_call_without_an_id_stays_uncoalesced(tmp_path):
    """Verify a CLI version that omits the id yields "", leaving every event counted."""
    driver = CodexCliDriver(tmp_path, slot="writer")
    line = '{"type": "item.completed", "item": {"type": "command_execution"}}'

    event = driver.parse_event(line, "harness-001", 1)

    assert event is not None
    assert event.payload["item_id"] == ""


def _git(root, *args):
    """Run a git command in a throwaway repo."""
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def test_capture_workspace_evidence_records_real_diff(tmp_path):
    """Verify workspace evidence captures a real git diff and content hash."""
    if _git(tmp_path, "init").returncode != 0:
        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("print('v1')\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    baseline = capture_baseline(tmp_path)
    (tmp_path / "app.py").write_text("print('v2')\n")

    evidence = capture_workspace_evidence(tmp_path, baseline, "loop-run-001", "iteration-001")

    assert baseline.is_git_repo
    assert "app.py" in evidence.changed_files
    assert evidence.content_hash is not None
    assert evidence.content_hash.startswith("sha256:")
    assert evidence.diff_path is not None and evidence.diff_path.exists()


def test_capture_workspace_evidence_records_untracked_files(tmp_path):
    """Verify workspace evidence includes untracked files from a clean baseline."""
    if _git(tmp_path, "init").returncode != 0:
        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("print('v1')\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    baseline = capture_baseline(tmp_path)
    (tmp_path / "new_file.py").write_text("print('new')\n")

    evidence = capture_workspace_evidence(tmp_path, baseline, "loop-run-001", "iteration-001")

    assert "new_file.py" in evidence.changed_files
    assert evidence.diff_path is not None and evidence.diff_path.exists()
    assert "Untracked files:" in evidence.diff_text


def test_require_clean_baseline_rejects_dirty_workspace(tmp_path):
    """Verify dirty git state blocks live writer dispatch."""
    if _git(tmp_path, "init").returncode != 0:
        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("print('v1')\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "app.py").write_text("print('dirty')\n")

    baseline = capture_baseline(tmp_path)

    with pytest.raises(WorkspaceDirtyError):
        require_clean_baseline(baseline)


def test_add_provider_profile_rejects_fake_profile(tmp_path):
    """Verify provider add rejects the removed fake provider."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    result = add_provider_profile(connection, "fake", now=datetime(2026, 7, 7, tzinfo=UTC))
    profiles = load_provider_profiles(connection)

    assert not result.created
    assert result.profile is None
    assert profiles == []
    assert "Unknown provider" in result.message


def test_add_provider_profile_rejects_broken_cli(tmp_path, monkeypatch):
    """Verify provider add refuses a CLI whose version command exits non-zero."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    class Completed:
        """Describe a failed subprocess result for CLI detection."""

        returncode = 1
        stdout = ""
        stderr = "spawn ENOENT"

    monkeypatch.setattr("curator.providers.setup.shutil.which", lambda binary: binary)
    monkeypatch.setattr(
        "curator.providers.setup.subprocess.run", lambda *args, **kwargs: Completed()
    )

    result = add_provider_profile(connection, "codex")

    assert not result.created
    assert result.profile is None
    assert "unavailable" in result.message
    assert "spawn ENOENT" in result.message


def test_add_provider_profile_rejects_unknown_alias(tmp_path):
    """Verify an unknown provider alias is rejected."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    result = add_provider_profile(connection, "gpt5")

    assert not result.created
    assert "Unknown provider" in result.message


def _writer_step() -> CompiledLoopStep:
    """Return a writer-slot provider step for resolution tests."""
    return CompiledLoopStep(
        id="step-writer",
        role_id="engineer",
        task_id="task-writer",
        task_title="Write",
        sequence=1,
        step_type=LoopStepType.IMPLEMENT,
        role=RoleName.ENGINEER,
        decision_on_success=LoopDecisionType.CONTINUE,
        executor=StepExecutorType.PROVIDER,
        slot="writer",
    )


def test_resolve_provider_for_step_requires_real_provider(tmp_path):
    """Verify an unbound writer slot no longer resolves to a fake driver."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    ensure_default_role_pool(connection)

    with pytest.raises(ProviderConfigurationError):
        resolve_provider_for_step(connection, _writer_step(), tmp_path)


def test_resolve_provider_for_step_uses_bound_profile(tmp_path):
    """Verify a bound writer slot resolves to the provider's driver."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    ensure_default_role_pool(connection)
    _seed_codex_profile(connection)
    _bind_writer_to_codex(connection)

    driver = resolve_provider_for_step(connection, _writer_step(), tmp_path)

    assert isinstance(driver, CodexCliDriver)
    assert driver.slot == "writer"


def _seed_codex_profile(connection) -> None:
    """Insert a codex provider profile directly, bypassing CLI detection."""
    from curator.core.schema import ProviderProfileRecord
    from curator.state.repositories import insert_provider_profile

    now = datetime(2026, 7, 7, tzinfo=UTC)
    insert_provider_profile(
        connection,
        ProviderProfileRecord(
            id="codex",
            provider=ProviderName.CODEX,
            label="codex (local CLI)",
            credential_ref="local-cli",
            status=ProviderProfileStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        ),
    )


def _bind_writer_to_codex(connection) -> None:
    """Bind the default writer slot instance to the codex profile."""
    from curator.core.enums import ProviderBindingStatus
    from curator.core.schema import RoleProviderBindingRecord

    now = datetime(2026, 7, 7, tzinfo=UTC)
    insert_role_provider_binding(
        connection,
        RoleProviderBindingRecord(
            id="binding-writer-codex",
            role_instance_id="writer.default",
            provider_profile_id="codex",
            status=ProviderBindingStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        ),
    )


def test_capture_baseline_ignores_curator_state_dir(tmp_path):
    """Verify Curator's own .curator/ state never marks the workspace dirty."""
    if _git(tmp_path, "init").returncode != 0:
        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")

    # Simulate `curator init` creating local state in the target repo.
    (tmp_path / ".curator").mkdir()
    (tmp_path / ".curator" / "curator.sqlite").write_text("x")

    baseline = capture_baseline(tmp_path)
    assert baseline.is_git_repo
    assert baseline.clean  # .curator/ must not count as a dirty workspace

    # A real source change still trips the guard.
    (tmp_path / "app.py").write_text("print('x')\n")
    dirty = capture_baseline(tmp_path)
    assert not dirty.clean

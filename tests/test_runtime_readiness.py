"""Verify provider-readiness runtime state and user shell behavior."""

from datetime import UTC, datetime
from pathlib import Path

from curator.app import start_goal_loop, write_init_state
from curator.context.packaging import build_context_package, build_pm_research_packet
from curator.core.enums import LoopStepType, ProviderName, RoleName
from curator.core.paths import build_curator_paths
from curator.core.schema import HarnessRunSpec, QAValidationOutput
from curator.goals.store import accept_goal, propose_goal, save_goal
from curator.providers.contracts import (
    HandoffRequest,
    ProviderErrorKind,
    ProviderCancelledError,
    ProviderRunRequest,
    ProviderRunResponse,
    ScopeChangeSignal,
)
from fakes import CodingDeliveryFakeProvider, enable_live_mode, install_fake_claude
from curator.runtime.action_policy import ActionPolicy, ActionRequest, ActionType
from curator.scheduler.snapshots import load_latest_workflow_snapshot
from curator.shell.repl import ShellState, handle_shell_input
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    load_context_packages_for_run,
    load_goal_draft_for_discovery,
    load_latest_discovery_session,
    load_latest_pause_record,
    load_pause_records_for_run,
    load_provider_runs_for_run,
    load_resume_events_for_pause,
)


class AlwaysFailValidationProvider(CodingDeliveryFakeProvider):
    """Return failed QA validation for every validation step."""

    def run(self, spec: HarnessRunSpec):
        """Return deterministic repeated validation failure."""
        if spec.step_type is LoopStepType.VALIDATE:
            return QAValidationOutput(
                passed=False,
                summary="Fake QA validation still failed.",
                checks=["tests-failed"],
            )

        return super().run(spec)


def _accepted_goal_revision(project_root: Path, text: str = "Fix mobile login layout") -> str:
    """Create and accept one deterministic goal revision."""
    paths = build_curator_paths(project_root)
    write_init_state(project_root)
    goal = propose_goal(text)
    save_goal(paths, goal)
    return accept_goal(paths, goal.id).revision_id


def test_shell_recovers_goal_draft_and_history_from_sqlite(tmp_path):
    """Verify PM discovery discussion survives shell restart before goal acceptance."""
    enable_live_mode(tmp_path)
    first_state = ShellState(project_root=tmp_path, gate_mode=True)

    draft_response = handle_shell_input(first_state, "Fix mobile login layout")
    build_curator_paths(tmp_path).goal_file("goal-fix-mobile-login-layout").unlink()
    recovered_goal = handle_shell_input(ShellState(project_root=tmp_path), "/goal current")
    recovered_history = handle_shell_input(ShellState(project_root=tmp_path), "/history")

    assert "PM drafted a goal contract:" in draft_response.text
    assert "Draft goal:" in recovered_goal.text
    assert "Fix mobile login layout" in recovered_goal.text
    assert "Discovery discussion:" in recovered_history.text
    assert "user: Fix mobile login layout" in recovered_history.text

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    discovery = load_latest_discovery_session(connection, str(tmp_path))
    draft = load_goal_draft_for_discovery(connection, discovery.id)
    connection.close()

    assert draft.goal_id == "goal-fix-mobile-login-layout"
    assert draft.contract["summary"] == "Fix mobile login layout"


def test_goal_current_prefers_accepted_revision_after_loop_start(tmp_path, monkeypatch):
    """Verify accepted goals take precedence over stale draft recovery."""
    enable_live_mode(tmp_path)
    install_fake_claude(tmp_path, monkeypatch)
    state = ShellState(project_root=tmp_path, gate_mode=True)

    handle_shell_input(state, "Fix mobile login layout")
    handle_shell_input(state, "yes")
    recovered_goal = handle_shell_input(ShellState(project_root=tmp_path), "/goal current")

    assert "Accepted goal:" in recovered_goal.text
    assert "Revision: goal-fix-mobile-login-layout-rev-001" in recovered_goal.text
    assert "Draft goal:" not in recovered_goal.text


def test_shell_accepts_recovered_goal_draft_after_restart(tmp_path, monkeypatch):
    """Verify /goal start accepts the latest SQLite draft without ShellState cache."""
    enable_live_mode(tmp_path)
    install_fake_claude(tmp_path, monkeypatch)
    handle_shell_input(
        ShellState(project_root=tmp_path, gate_mode=True), "Fix mobile login layout"
    )

    guided = handle_shell_input(ShellState(project_root=tmp_path), "yes")
    accepted = handle_shell_input(ShellState(project_root=tmp_path), "/goal start")
    current = handle_shell_input(ShellState(project_root=tmp_path), "/goal current")

    assert "No pending proposal" in guided.text
    assert "/goal start" in guided.text
    assert "Goal accepted:" in accepted.text
    assert "Accepted goal:" in current.text
    assert "goal-fix-mobile-login-layout-rev-001" in current.text


def test_paused_node_and_resume_are_durable_across_shell_restart(tmp_path):
    """Verify paused node context and resume answers are recovered from SQLite."""
    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(
        tmp_path,
        revision_id,
        provider=AlwaysFailValidationProvider(),
    )
    loop_run = snapshot.loop_runs[-1]

    node_response = handle_shell_input(ShellState(project_root=tmp_path), "/node current")
    notice_response = handle_shell_input(
        ShellState(project_root=tmp_path),
        "Please keep scope and repair only the failing validation.",
    )
    resume_response = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/resume Please keep scope and repair only the failing validation.",
    )

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    pauses = load_pause_records_for_run(connection, loop_run.id)
    resume_events = load_resume_events_for_pause(connection, pauses[0].id)
    recovered = load_latest_workflow_snapshot(connection)
    connection.close()

    assert "Role: qa" in node_response.text
    assert "Verify the implementation" in node_response.text
    assert "Paused:" in node_response.text
    assert "No verification commands were found" in node_response.text
    assert "A loop is paused:" in notice_response.text
    assert "/resume" in notice_response.text
    assert "/revise" in notice_response.text
    # Executable resume replays the ledger, so the loop continues instead of
    # merely recording the answer.
    assert "Resumed." in resume_response.text
    assert pauses[0].question == "How should Curator proceed from this paused node?"
    assert pauses[0].status.value == "resolved"
    assert resume_events[0].message == "Please keep scope and repair only the failing validation."
    assert len(recovered.loop_iterations) >= len(snapshot.loop_iterations)


def test_revise_command_creates_revised_goal_draft_from_pause(tmp_path):
    """Verify /revise drafts a durable revised goal instead of a resume event."""
    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(
        tmp_path,
        revision_id,
        provider=AlwaysFailValidationProvider(),
    )
    loop_run = snapshot.loop_runs[-1]

    response = handle_shell_input(
        ShellState(project_root=tmp_path),
        "/revise Change scope to also refactor checkout",
    )
    current = handle_shell_input(ShellState(project_root=tmp_path), "/goal current")

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    pause = load_latest_pause_record(connection, loop_run.id)
    resume_events = load_resume_events_for_pause(connection, pause.id)
    discovery = load_latest_discovery_session(connection, str(tmp_path))
    draft = load_goal_draft_for_discovery(connection, discovery.id)
    connection.close()

    assert "PM drafted a revised goal proposal:" in response.text
    assert "Change scope to also refactor checkout" in current.text
    assert resume_events == []
    assert draft.contract["metadata"]["scope_change_from_pause_id"] == pause.id


def test_cancel_resolves_paused_loop_cursor(tmp_path):
    """Verify /cancel records user cancellation for a paused loop."""
    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(
        tmp_path,
        revision_id,
        provider=AlwaysFailValidationProvider(),
    )
    loop_run = snapshot.loop_runs[-1]

    response = handle_shell_input(ShellState(project_root=tmp_path), "/cancel")
    node = handle_shell_input(ShellState(project_root=tmp_path), "/workbench")

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    pauses = load_pause_records_for_run(connection, loop_run.id)
    resume_events = load_resume_events_for_pause(connection, pauses[0].id)
    latest_pause = load_latest_pause_record(connection, loop_run.id)
    connection.close()

    assert "Paused loop cancelled." in response.text
    assert pauses[0].status.value == "resolved"
    assert resume_events[0].action == "cancel"
    assert latest_pause is None
    assert "Paused:\n- none" in node.text


def test_provider_run_contract_and_ledger_capture_scheduler_owned_decisions(tmp_path):
    """Verify provider runs are typed and scheduler decisions remain separate."""
    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(tmp_path, revision_id, provider=CodingDeliveryFakeProvider())
    loop_run = snapshot.loop_runs[-1]
    first_iteration = snapshot.loop_iterations[0]

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)
    context_packages = load_context_packages_for_run(connection, loop_run.id)
    connection.close()

    request = ProviderRunRequest.from_harness_spec(
        HarnessRunSpec(
            id="harness-contract",
            session_id="session-contract",
            loop_run_id="loop-run-contract",
            iteration_id="iteration-contract",
            role=RoleName.PM,
            step_type=LoopStepType.PLAN,
            task_id="task-contract",
        )
    )
    response = ProviderRunResponse.succeeded(
        request=request,
        provider=ProviderName.CODEX,
        output={"summary": "ok"},
    )

    assert request.allowed_actions
    assert response.error_kind is None
    assert provider_runs[0].provider is ProviderName.CODEX
    assert provider_runs[0].role is RoleName.ENGINEER
    assert provider_runs[0].error_kind is None
    assert provider_runs[0].response["status"] == "succeeded"
    assert provider_runs[0].metadata["scheduler_decision"] == "continue"
    assert context_packages[0].iteration_id == first_iteration.id


def test_provider_handoff_signal_pauses_without_provider_stop_decision(tmp_path):
    """Verify provider handoff signals are ledgered and scheduler-owned."""

    class HandoffProvider:
        """Return a typed handoff signal instead of role output."""

        def run(self, spec: HarnessRunSpec):
            """Return a provider response requesting user clarification."""
            request = ProviderRunRequest.from_harness_spec(spec)
            return ProviderRunResponse.succeeded(
                request=request,
                provider=ProviderName.CODEX,
                output={"summary": "needs clarification"},
            ).model_copy(
                update={
                    "handoff_request": HandoffRequest(
                        reason="Need user clarification.",
                        question="Which login viewport should be prioritized?",
                        requested_input="viewport priority",
                    )
                }
            )

    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(tmp_path, revision_id, provider=HandoffProvider())
    loop_run = snapshot.loop_runs[-1]

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)
    pause = load_latest_pause_record(connection, loop_run.id)
    connection.close()

    assert loop_run.status.value == "paused"
    assert provider_runs[0].status.value == "succeeded"
    assert provider_runs[0].response["handoff_request"]["question"] == (
        "Which login viewport should be prioritized?"
    )
    assert provider_runs[0].metadata["scheduler_decision"] == "human_handoff"
    assert pause.reason == "Need user clarification."


def test_provider_scope_change_signal_pauses_without_revising_goal(tmp_path):
    """Verify provider scope signals pause and wait for user-owned revision."""

    class ScopeChangeProvider:
        """Return a typed scope-change signal instead of role output."""

        def run(self, spec: HarnessRunSpec):
            """Return a provider response suggesting revised scope."""
            request = ProviderRunRequest.from_harness_spec(spec)
            return ProviderRunResponse.succeeded(
                request=request,
                provider=ProviderName.CODEX,
                output={"summary": "scope changed"},
            ).model_copy(
                update={
                    "scope_change": ScopeChangeSignal(
                        summary="User request now includes checkout refactor.",
                        recommendation="create_goal_revision",
                    )
                }
            )

    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(tmp_path, revision_id, provider=ScopeChangeProvider())
    loop_run = snapshot.loop_runs[-1]

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)
    pause = load_latest_pause_record(connection, loop_run.id)
    connection.close()

    assert loop_run.status.value == "paused"
    assert provider_runs[0].response["scope_change"]["summary"] == (
        "User request now includes checkout refactor."
    )
    assert provider_runs[0].metadata["scheduler_decision"] == "human_handoff"
    assert pause.reason == "Scope change suggested: User request now includes checkout refactor."


def test_context_packaging_builds_pm_research_packet_from_evidence(tmp_path):
    """Verify PM receives evidence-backed research instead of raw shared history."""
    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(tmp_path, revision_id, provider=CodingDeliveryFakeProvider())
    loop_run = snapshot.loop_runs[-1]
    qa_iteration = next(
        iteration
        for iteration in snapshot.loop_iterations
        if iteration.step_type is LoopStepType.VALIDATE
    )

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    package = build_context_package(
        connection,
        session_id=snapshot.session.id,
        loop_run_id=loop_run.id,
        iteration_id=qa_iteration.id,
        role=RoleName.PM,
        task_id=qa_iteration.task_id,
        project_root=tmp_path,
    )
    research = build_pm_research_packet(connection, project_root=tmp_path)
    connection.close()

    assert package.role is RoleName.PM
    assert package.goal_snapshot["summary"] == "Fix mobile login layout"
    assert "implementation" in research.evidence_summaries
    assert "validation" in research.evidence_summaries
    assert research.unknowns == []


def test_context_packaging_marks_missing_evidence_as_unknown(tmp_path):
    """Verify PM research does not invent implementation state without evidence."""
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)

    research = build_pm_research_packet(connection, project_root=tmp_path)
    connection.close()

    assert "implementation evidence is not available" in research.unknowns
    assert "validation evidence is not available" in research.unknowns


def test_action_policy_blocks_out_of_scope_and_destructive_actions(tmp_path):
    """Verify provider actions are checked before any real adapter can execute them."""
    policy = ActionPolicy.for_project(tmp_path)

    allowed_read = policy.evaluate(
        ActionRequest(type=ActionType.READ_FILE, target=str(tmp_path / "README.md"))
    )
    outside_write = policy.evaluate(
        ActionRequest(type=ActionType.WRITE_FILE, target="/private/etc/passwd")
    )
    destructive_shell = policy.evaluate(
        ActionRequest(type=ActionType.SHELL_COMMAND, command="rm -rf .curator")
    )
    github_write = policy.evaluate(
        ActionRequest(type=ActionType.VCS_REMOTE_WRITE, target="github://pull-request")
    )

    assert allowed_read.allowed is True
    assert outside_write.allowed is False
    assert outside_write.handoff_required is True
    assert destructive_shell.approval_required is True
    assert github_write.approval_required is True
    assert github_write.reason == "Remote VCS write actions require user approval."


def test_provider_failure_matrix_records_typed_invalid_output(tmp_path):
    """Verify invalid provider output pauses with a typed provider ledger error."""

    class InvalidOutputProvider:
        """Return an invalid provider payload that cannot satisfy the contract."""

        def run(self, spec: HarnessRunSpec):
            """Return a non-schema payload for failure-matrix coverage."""
            _ = spec
            return {"summary": "not a role output"}

    now = datetime(2026, 7, 7, tzinfo=UTC)
    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(
        tmp_path,
        revision_id,
        provider=InvalidOutputProvider(),
    )
    _ = now
    loop_run = snapshot.loop_runs[-1]

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)
    pause = load_latest_pause_record(connection, loop_run.id)
    connection.close()

    assert loop_run.status.value == "paused"
    assert provider_runs[0].error_kind is ProviderErrorKind.INVALID_OUTPUT
    assert "Unsupported provider output" in provider_runs[0].error_message
    assert pause.reason == "Provider invalid output; pausing for user input."


def test_provider_failure_matrix_records_cancelled_timeout_and_permission(tmp_path):
    """Verify common provider failures pause with typed ledger entries."""

    class RaisingProvider:
        """Raise a configured provider exception for failure-matrix coverage."""

        def __init__(self, error: Exception) -> None:
            """Store the exception this fake provider should raise."""
            self.error = error

        def run(self, spec: HarnessRunSpec):
            """Raise the configured exception instead of returning output."""
            _ = spec
            raise self.error

    cases = [
        (ProviderCancelledError("user interrupted provider"), ProviderErrorKind.CANCELLED),
        (TimeoutError("provider timed out"), ProviderErrorKind.TIMEOUT),
        (PermissionError("provider requested denied write"), ProviderErrorKind.PERMISSION_DENIED),
    ]

    for index, (error, expected_kind) in enumerate(cases):
        project = tmp_path / f"case-{index}"
        revision_id = _accepted_goal_revision(project, f"Fix mobile login layout {index}")
        snapshot = start_goal_loop(project, revision_id, provider=RaisingProvider(error))
        loop_run = snapshot.loop_runs[-1]

        connection = connect_database(build_curator_paths(project).database)
        initialize_database(connection)
        provider_runs = load_provider_runs_for_run(connection, loop_run.id)
        pause = load_latest_pause_record(connection, loop_run.id)
        connection.close()

        assert loop_run.status.value == "paused"
        assert provider_runs[0].error_kind is expected_kind
        assert pause is not None
        assert "pausing for user input" in pause.reason


def test_provider_failure_matrix_records_provider_unavailable(tmp_path):
    """Verify unavailable providers fail with typed ledger entries."""

    class UnavailableProvider:
        """Raise a generic provider availability failure."""

        def run(self, spec: HarnessRunSpec):
            """Raise a runtime error instead of returning role output."""
            _ = spec
            raise RuntimeError("provider service is unavailable")

    revision_id = _accepted_goal_revision(tmp_path)
    snapshot = start_goal_loop(tmp_path, revision_id, provider=UnavailableProvider())
    loop_run = snapshot.loop_runs[-1]

    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)
    pause = load_latest_pause_record(connection, loop_run.id)
    connection.close()

    assert loop_run.status.value == "paused"
    assert provider_runs[0].error_kind is ProviderErrorKind.PROVIDER_UNAVAILABLE
    assert provider_runs[0].metadata["scheduler_decision"] == "human_handoff"
    assert pause is not None


def test_workbench_surfaces_paused_provider_failure(tmp_path):
    """Verify users can see provider failure pause state in the workbench."""

    class TimeoutProvider:
        """Raise timeout to force a paused provider failure."""

        def run(self, spec: HarnessRunSpec):
            """Raise timeout instead of returning role output."""
            _ = spec
            raise TimeoutError("provider timed out")

    revision_id = _accepted_goal_revision(tmp_path)
    start_goal_loop(tmp_path, revision_id, provider=TimeoutProvider())

    workbench = handle_shell_input(ShellState(project_root=tmp_path), "/workbench")

    assert "Paused:" in workbench.text
    assert "Provider timed out; pausing for user input." in workbench.text
    assert "Next: /node current or /resume <message>" in workbench.text

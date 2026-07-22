"""Verify sequential workflow scheduling behavior."""

from datetime import UTC, datetime

from curator.core.enums import (
    EventType,
    EvidenceKind,
    HarnessStatus,
    LoopDecisionType,
    LoopStatus,
    LoopStepType,
    ProviderName,
    RoleName,
    StopCondition,
    TaskStatus,
)
from curator.core.schema import HarnessRunSpec, QAValidationOutput, RoleContract
from curator.loops.compiler import compile_coding_delivery_plan
from curator.providers.events import ProviderEvent, ProviderEventKind
from fakes import CodingDeliveryFakeProvider
from curator.scheduler.engine import create_workflow_session, run_workflow
from curator.roles.registry import default_role_contracts
from curator.state.db import CuratorConnection, connect_database, initialize_database
from curator.state.repositories import (
    load_events_for_session,
    load_evidence_refs_for_run,
    load_loop_decisions_for_run,
    load_loop_iterations_for_run,
    load_loop_runs_for_session,
    load_provider_runs_for_run,
    load_role_selections_for_run,
    load_session,
    load_tasks_for_session,
)


class RetryOnceCodingDeliveryFakeProvider(CodingDeliveryFakeProvider):
    """Return one failed QA validation before allowing retry success."""

    def __init__(self) -> None:
        """Track how many QA validation outputs have been returned."""
        self.validation_runs = 0

    def run(self, spec: HarnessRunSpec):
        """Return failed QA once, then delegate to the default fake provider."""
        if spec.step_type is LoopStepType.VALIDATE:
            self.validation_runs += 1
            if self.validation_runs == 1:
                return QAValidationOutput(
                    passed=False,
                    summary="Fake QA validation failed.",
                    checks=["tests-failed"],
                )

        return super().run(spec)


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


class FailingProvider:
    """Raise a provider error for every harness run."""

    def run(self, spec: HarnessRunSpec):
        """Raise a deterministic provider failure."""
        _ = spec
        raise RuntimeError("provider down")


class ProfiledCodingDeliveryFakeProvider(CodingDeliveryFakeProvider):
    """Expose provider identity attributes while returning fake outputs."""

    provider_name = ProviderName.CODEX
    provider_profile_id = "codex-work"
    provider_session_id = "provider-session-codex-work"


def test_create_workflow_session_writes_session_tasks_and_loop_run(tmp_path):
    """Verify scheduler can create the durable skeleton for a fake loop."""
    now = datetime(2026, 6, 25, 14, 0, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    session_id = create_workflow_session(connection, tmp_path, created_at=now)
    loop_runs = load_loop_runs_for_session(connection, session_id)
    tasks = load_tasks_for_session(connection, session_id)

    assert load_session(connection, session_id).project_root == tmp_path
    assert [task.role for task in tasks] == [
        RoleName.PM,
        RoleName.ENGINEER,
        RoleName.QA,
        RoleName.PM,
    ]
    assert [task.status for task in tasks] == [
        TaskStatus.QUEUED,
        TaskStatus.QUEUED,
        TaskStatus.QUEUED,
        TaskStatus.QUEUED,
    ]
    assert [task.title for task in tasks] == [
        "Plan coding delivery",
        "Implement coding delivery",
        "Validate coding delivery",
        "Confirm coding delivery",
    ]
    assert len(loop_runs) == 1
    assert loop_runs[0].template_id == "coding_delivery_loop"
    assert loop_runs[0].status is LoopStatus.RUNNING


def test_run_workflow_persists_provider_identity_from_provider(tmp_path):
    """Verify provider run ledger records provider profile identity."""
    now = datetime(2026, 7, 7, 14, 0, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)

    run_workflow(connection, session_id, ProfiledCodingDeliveryFakeProvider(), created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    provider_runs = load_provider_runs_for_run(connection, loop_run.id)

    assert provider_runs
    assert {run.provider for run in provider_runs} == {ProviderName.CODEX}
    assert {run.provider_profile_id for run in provider_runs} == {"codex-work"}
    assert {run.provider_session_id for run in provider_runs} == {
        "provider-session-codex-work"
    }


def test_create_workflow_session_generates_unique_ids_without_overwriting(tmp_path):
    """Verify repeated fake sessions keep separate durable records."""
    now = datetime(2026, 6, 25, 14, 5, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    first_session_id = create_workflow_session(connection, tmp_path, created_at=now)
    second_session_id = create_workflow_session(connection, tmp_path, created_at=now)
    first_tasks = load_tasks_for_session(connection, first_session_id)
    second_tasks = load_tasks_for_session(connection, second_session_id)
    first_loop_run = load_loop_runs_for_session(connection, first_session_id)[0]
    second_loop_run = load_loop_runs_for_session(connection, second_session_id)[0]

    assert first_session_id != second_session_id
    assert first_loop_run.id != second_loop_run.id
    assert len(first_tasks) == 4
    assert len(second_tasks) == 4
    assert {task.id for task in first_tasks}.isdisjoint(
        {task.id for task in second_tasks}
    )


def test_create_workflow_session_reuses_explicit_session_without_overwriting_loop_tasks(
    tmp_path,
):
    """Verify repeated explicit session runs keep separate loop-scoped tasks."""
    now = datetime(2026, 6, 25, 14, 6, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    session_id = create_workflow_session(
        connection,
        tmp_path,
        created_at=now,
        session_id="session-demo-001",
    )
    repeated_session_id = create_workflow_session(
        connection,
        tmp_path,
        created_at=now,
        session_id="session-demo-001",
    )
    loop_runs = load_loop_runs_for_session(connection, session_id)
    tasks = load_tasks_for_session(connection, session_id)

    assert session_id == repeated_session_id == "session-demo-001"
    assert len(loop_runs) == 2
    assert len(tasks) == 8
    assert len({task.id for task in tasks}) == 8


def test_create_workflow_session_uses_compiled_plan_step_contracts(tmp_path):
    """Verify scheduler creates tasks from a compiled plan rather than local step rules."""
    now = datetime(2026, 6, 25, 14, 10, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    compiled_plan = compile_coding_delivery_plan(
        session_id="session-001",
        contract_id="contract-coding-delivery",
    ).model_copy(
        update={
            "steps": [
                step.model_copy(update={"task_title": f"Compiled: {step.task_title}"})
                for step in compile_coding_delivery_plan(
                    session_id="session-001",
                    contract_id="contract-coding-delivery",
                ).steps
            ]
        }
    )

    session_id = create_workflow_session(
        connection,
        tmp_path,
        created_at=now,
        compiled_plan=compiled_plan,
    )
    tasks = load_tasks_for_session(connection, session_id)

    assert [task.title for task in tasks] == [
        "Compiled: Plan coding delivery",
        "Compiled: Implement coding delivery",
        "Compiled: Validate coding delivery",
        "Compiled: Confirm coding delivery",
    ]


def test_create_workflow_session_persists_selected_role_ledger(tmp_path):
    """Verify scheduler records why a compiled plan selected a dynamic role."""
    now = datetime(2026, 6, 25, 14, 20, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    contracts = default_role_contracts()
    contracts["security_reviewer"] = RoleContract(
        id="security_reviewer",
        display_name="Security Reviewer",
        responsibilities=["Review auth, token, secret, and permission boundaries."],
        when_to_involve=["auth", "secret", "permission"],
        expected_evidence_kinds=[EvidenceKind.ARTIFACT],
        forbidden_actions=["edit-product-scope"],
        capability_tags=["security-review", "auth", "secrets"],
    )
    compiled_plan = compile_coding_delivery_plan(
        session_id="session-001",
        contract_id="contract-coding-delivery",
        role_contracts=contracts,
        task_signals=["auth", "secret"],
    )

    session_id = create_workflow_session(
        connection,
        tmp_path,
        created_at=now,
        compiled_plan=compiled_plan,
    )
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    selections = load_role_selections_for_run(connection, loop_run.id)

    assert len(selections) == 1
    assert selections[0].role_id == "security_reviewer"
    assert selections[0].display_name == "Security Reviewer"
    assert selections[0].matched_signals == ["auth", "secret"]
    assert selections[0].score == 2
    assert selections[0].reason == (
        "Selected security_reviewer because it matched: auth, secret."
    )


def test_run_workflow_writes_four_step_loop_ledger(tmp_path):
    """Verify scheduler drives PM, Engineer, QA, and PM confirmation ledger writes."""
    now = datetime(2026, 6, 25, 14, 30, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)

    run_workflow(connection, session_id, CodingDeliveryFakeProvider(), created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    iterations = load_loop_iterations_for_run(connection, loop_run.id)
    decisions = load_loop_decisions_for_run(connection, loop_run.id)
    evidence_refs = load_evidence_refs_for_run(connection, loop_run.id)
    tasks = load_tasks_for_session(connection, session_id)

    assert loop_run.status is LoopStatus.DONE
    assert [task.status for task in tasks] == [
        TaskStatus.DONE,
        TaskStatus.DONE,
        TaskStatus.DONE,
        TaskStatus.DONE,
    ]
    assert [iteration.step_type for iteration in iterations] == [
        LoopStepType.PLAN,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.CONFIRM,
    ]
    assert [evidence.kind for evidence in evidence_refs] == [
        EvidenceKind.PLAN,
        EvidenceKind.IMPLEMENTATION,
        EvidenceKind.VALIDATION,
        EvidenceKind.PM_CONFIRMATION,
    ]
    assert [decision.decision for decision in decisions] == [
        LoopDecisionType.CONTINUE_TO_ENGINEER,
        LoopDecisionType.CONTINUE_TO_QA,
        LoopDecisionType.CONTINUE_TO_PM,
        LoopDecisionType.STOP_DONE,
    ]
    assert [decision.reason for decision in decisions] == [
        "Start implementation after PM scope and acceptance criteria are clear.",
        "Validate implementation before PM confirmation.",
        "Send passing validation evidence for final product confirmation.",
        "Complete the loop after PM confirms QA evidence.",
    ]
    assert decisions[-1].stop_condition is StopCondition.DONE_CRITERIA_MET


def test_run_workflow_retries_engineer_after_failed_qa_validation(tmp_path):
    """Verify scheduler routes failed QA validation back through Engineer once."""
    now = datetime(2026, 6, 25, 14, 40, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)

    run_workflow(connection, session_id, RetryOnceCodingDeliveryFakeProvider(), created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    iterations = load_loop_iterations_for_run(connection, loop_run.id)
    decisions = load_loop_decisions_for_run(connection, loop_run.id)
    evidence_refs = load_evidence_refs_for_run(connection, loop_run.id)

    assert loop_run.status is LoopStatus.DONE
    assert [iteration.step_type for iteration in iterations] == [
        LoopStepType.PLAN,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.CONFIRM,
    ]
    assert [decision.decision for decision in decisions] == [
        LoopDecisionType.CONTINUE_TO_ENGINEER,
        LoopDecisionType.CONTINUE_TO_QA,
        LoopDecisionType.RETRY_IMPLEMENTATION,
        LoopDecisionType.CONTINUE_TO_QA,
        LoopDecisionType.CONTINUE_TO_PM,
        LoopDecisionType.STOP_DONE,
    ]
    assert decisions[2].reason == (
        "Return failed validation feedback for implementation repair."
    )
    assert decisions[2].stop_condition is StopCondition.VALIDATION_FAILED
    assert len(evidence_refs) == 6


def test_run_workflow_pauses_after_repeated_validation_failure(tmp_path):
    """Verify repeated validation failure pauses for user input instead of failing."""
    now = datetime(2026, 6, 25, 14, 45, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)

    run_workflow(connection, session_id, AlwaysFailValidationProvider(), created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    decisions = load_loop_decisions_for_run(connection, loop_run.id)

    assert loop_run.status is LoopStatus.PAUSED
    assert loop_run.completed_at is None
    assert decisions[-1].decision is LoopDecisionType.HUMAN_HANDOFF
    assert decisions[-1].stop_condition is StopCondition.HUMAN_HANDOFF_REQUESTED
    assert decisions[-1].reason == (
        "Repeated validation failure; pausing for user input."
    )


def test_run_workflow_stops_failed_when_provider_raises(tmp_path):
    """Verify scheduler persists provider failure decisions instead of raising."""
    now = datetime(2026, 6, 25, 14, 50, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)

    run_workflow(connection, session_id, FailingProvider(), created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    iterations = load_loop_iterations_for_run(connection, loop_run.id)
    decisions = load_loop_decisions_for_run(connection, loop_run.id)
    tasks = load_tasks_for_session(connection, session_id)

    assert loop_run.status is LoopStatus.FAILED
    assert len(iterations) == 1
    assert iterations[0].status is HarnessStatus.FAILED
    assert decisions[0].decision is LoopDecisionType.STOP_FAILED
    assert decisions[0].stop_condition is StopCondition.PROVIDER_FAILED
    assert tasks[0].status is TaskStatus.FAILED


class RecordingRetryProvider(RetryOnceCodingDeliveryFakeProvider):
    """Record harness specs while failing QA validation once."""

    def __init__(self) -> None:
        """Track validation failures and observed harness specs."""
        super().__init__()
        self.specs = []

    def run(self, spec: HarnessRunSpec):
        """Record the spec before delegating to the retry-once provider."""
        self.specs.append(spec)
        return super().run(spec)


def test_run_workflow_retry_context_includes_failed_validation_evidence(tmp_path):
    """Verify the retried implementation step can see why validation failed."""
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)
    provider = RecordingRetryProvider()

    run_workflow(connection, session_id, provider, created_at=now)
    implement_specs = [
        spec for spec in provider.specs if spec.step_type is LoopStepType.IMPLEMENT
    ]

    assert len(implement_specs) == 2
    first_kinds = [evidence.kind for evidence in implement_specs[0].context_refs]
    retry_kinds = [evidence.kind for evidence in implement_specs[1].context_refs]
    assert EvidenceKind.VALIDATION not in first_kinds
    assert EvidenceKind.VALIDATION in retry_kinds


def test_run_workflow_uses_fresh_timestamps_per_iteration(tmp_path):
    """Verify iterations record real durations instead of one shared timestamp."""
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path)

    run_workflow(connection, session_id, CodingDeliveryFakeProvider())
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    iterations = load_loop_iterations_for_run(connection, loop_run.id)

    assert len(iterations) == 4
    started_values = {iteration.started_at for iteration in iterations}
    assert len(started_values) > 1
    for iteration in iterations:
        assert iteration.completed_at is not None
        assert iteration.completed_at >= iteration.started_at


def test_run_workflow_pauses_with_max_iterations_stop_condition(tmp_path):
    """Verify the iteration budget converts endless retries into a pause."""
    now = datetime(2026, 6, 25, 15, 10, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    plan = compile_coding_delivery_plan(
        session_id="session-max-iterations",
        contract_id="contract-coding-delivery",
    )
    plan = plan.model_copy(
        update={
            "steps": [
                step.model_copy(update={"metadata": {**step.metadata, "max_retries": 99}})
                if step.step_type is LoopStepType.IMPLEMENT
                else step
                for step in plan.steps
            ]
        }
    )
    session_id = create_workflow_session(
        connection, tmp_path, created_at=now, compiled_plan=plan
    )

    run_workflow(
        connection,
        session_id,
        AlwaysFailValidationProvider(),
        created_at=now,
        compiled_plan=plan,
    )
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    iterations = load_loop_iterations_for_run(connection, loop_run.id)
    decisions = load_loop_decisions_for_run(connection, loop_run.id)

    assert loop_run.status is LoopStatus.PAUSED
    assert 10 <= len(iterations) <= 12
    assert decisions[-1].decision is LoopDecisionType.HUMAN_HANDOFF
    assert decisions[-1].stop_condition is StopCondition.MAX_ITERATIONS_REACHED


def test_create_workflow_session_persists_compiled_plan_for_resume(tmp_path):
    """Verify the compiled plan round-trips through loop_runs metadata."""
    from curator.scheduler.engine import load_compiled_plan_for_run

    now = datetime(2026, 6, 25, 15, 20, tzinfo=UTC)
    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)

    session_id = create_workflow_session(connection, tmp_path, created_at=now)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    restored = load_compiled_plan_for_run(loop_run)

    assert restored is not None
    assert restored.session_id == session_id
    assert [step.step_type for step in restored.steps] == [
        LoopStepType.PLAN,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.CONFIRM,
    ]
    assert restored.steps[0].task_id


class _StreamingChunkDriver:
    """Async driver that streams a configurable number of OUTPUT_CHUNK events per step.

    It delegates the real role output to a wrapped synchronous fake so the loop still
    runs a full successful coding-delivery cycle; only the streamed chunk volume varies.
    """

    def __init__(self, inner: CodingDeliveryFakeProvider, chunk_count: int) -> None:
        """Wrap one sync provider and fix how many chunks to stream per step."""
        self._inner = inner
        self._chunk_count = chunk_count
        self.provider_name = inner.provider_name
        self.provider_profile_id = getattr(inner, "provider_profile_id", None)
        self.provider_session_id = getattr(inner, "provider_session_id", None)
        self.quota_status = getattr(inner, "quota_status", None)

    async def run(self, spec, request, on_event=None):
        """Stream chunk events, then return the wrapped provider's role output."""
        for index in range(self._chunk_count):
            if on_event is not None:
                on_event(
                    ProviderEvent(
                        kind=ProviderEventKind.OUTPUT_CHUNK,
                        provider_run_id=spec.id,
                        sequence=index + 1,
                        payload={"text": f"chunk-{index}"},
                    )
                )
        return self._inner.run(spec)


def test_provider_streaming_coalesces_ledger_commits(tmp_path, monkeypatch):
    """Verify streamed provider events commit once per step, not once per chunk.

    Running the same workflow with a small vs a large chunk volume must issue the same
    number of SQLite commits; if streaming committed per chunk, the counts would diverge.
    """
    now = datetime(2026, 6, 25, 14, 30, tzinfo=UTC)
    counter = {"commits": 0}
    original_commit = CuratorConnection.commit

    def counting_commit(self):
        """Count each real SQLite commit issued on a Curator connection."""
        counter["commits"] += 1
        return original_commit(self)

    monkeypatch.setattr(CuratorConnection, "commit", counting_commit)

    def _run_and_count(subdir: str, chunk_count: int) -> int:
        """Run one full workflow streaming chunk_count events per step and count commits."""
        connection = connect_database(tmp_path / subdir / "curator.sqlite")
        initialize_database(connection)
        session_id = create_workflow_session(connection, tmp_path / subdir, created_at=now)
        counter["commits"] = 0
        run_workflow(
            connection,
            session_id,
            _StreamingChunkDriver(CodingDeliveryFakeProvider(), chunk_count),
            created_at=now,
        )
        connection.close()
        return counter["commits"]

    assert _run_and_count("few", 5) == _run_and_count("many", 200)


class _StreamThenFailDriver:
    """Stream OUTPUT_CHUNK events, then raise as if the provider run failed."""

    def __init__(self, chunk_count: int = 4) -> None:
        """Fix how many diagnostic chunks stream before the run fails."""
        self._chunk_count = chunk_count
        self.provider_name = ProviderName.CLAUDE_CODE
        self.provider_profile_id = None
        self.provider_session_id = None
        self.quota_status = None

    async def run(self, spec, request, on_event=None):
        """Stream chunks, then raise a timeout to model a mid-run provider failure."""
        for index in range(self._chunk_count):
            if on_event is not None:
                on_event(
                    ProviderEvent(
                        kind=ProviderEventKind.OUTPUT_CHUNK,
                        provider_run_id=spec.id,
                        sequence=index + 1,
                        payload={"text": f"diagnostic-chunk-{index}"},
                    )
                )
        raise TimeoutError("Provider run timed out after 1800s")


def test_streamed_transcript_persists_when_provider_fails(tmp_path):
    """Verify a failed provider run keeps its streamed transcript on the ledger.

    The failing run is exactly the one whose output matters most for debugging, so its
    OUTPUT_CHUNK events must survive the provider error instead of rolling back with the
    step transaction. The loop still pauses for human handoff as before.
    """
    now = datetime(2026, 6, 25, 14, 30, tzinfo=UTC)
    connection = connect_database(tmp_path / "curator.sqlite")
    initialize_database(connection)
    session_id = create_workflow_session(connection, tmp_path, created_at=now)

    run_workflow(connection, session_id, _StreamThenFailDriver(chunk_count=4), created_at=now)

    events = load_events_for_session(connection, session_id)
    output_chunks = [
        event for event in events if event.type is EventType.PROVIDER_OUTPUT_CHUNK
    ]
    loop_run = load_loop_runs_for_session(connection, session_id)[-1]
    connection.close()

    assert len(output_chunks) == 4
    assert loop_run.status is LoopStatus.PAUSED

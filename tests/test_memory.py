"""Verify default memory files and the runtime memory learning loop."""

from datetime import UTC, datetime

from curator.context.packaging import build_context_package
from curator.core.enums import (
    EvidenceKind,
    HarnessStatus,
    LoopDecisionType,
    LoopStepType,
    RoleName,
)
from curator.core.paths import build_curator_paths
from curator.core.schema import (
    EvidenceRef,
    HarnessRunSpec,
    LoopDecisionRecord,
    LoopIterationRecord,
    MemoryEntryRecord,
    QAValidationOutput,
)
from curator.memory.distill import record_decision_memory
from fakes import CodingDeliveryFakeProvider
from curator.scheduler.engine import create_workflow_session, run_workflow
from curator.shell.repl import ShellState, handle_shell_input
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_memory_entry,
    load_loop_runs_for_session,
    load_memory_entries,
)
from curator.team.memory import default_memory_documents, write_default_memory


class _AlwaysFailValidationProvider(CodingDeliveryFakeProvider):
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


def test_default_memory_documents_use_required_html_sections():
    """Verify default memory documents follow the Curator document contract."""
    memory = default_memory_documents()

    assert "project" in memory
    assert "conventions" in memory
    assert f"roles/{RoleName.PM.value}" in memory
    for content in memory.values():
        assert "<h2>What</h2>" in content
        assert "<h2>How</h2>" in content
        assert "<h2>Why</h2>" in content
        assert "<h2>Future improvements/considerations/trade-offs</h2>" in content


def test_write_default_memory_creates_memory_files_without_overwriting(tmp_path):
    """Verify default memory files are created without replacing existing files."""
    paths = build_curator_paths(tmp_path)
    existing_memory = paths.memory_dir / "project.md"
    existing_memory.parent.mkdir(parents=True)
    existing_memory.write_text("<h1>custom project memory</h1>\n")

    written = write_default_memory(paths)

    assert paths.memory_dir / "conventions.md" in written
    assert paths.role_memory_file(RoleName.ENGINEER) in written
    assert existing_memory not in written
    assert existing_memory.read_text() == "<h1>custom project memory</h1>\n"


def _memory_connection(tmp_path):
    """Open an initialized Curator database for memory tests."""
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    return connection


def test_record_decision_memory_writes_failure_lesson(tmp_path):
    """Verify retry decisions are distilled into durable memory entries."""
    now = datetime(2026, 7, 7, 10, 0, tzinfo=UTC)
    connection = _memory_connection(tmp_path)
    iteration = LoopIterationRecord(
        id="iteration-001",
        loop_run_id="loop-run-001",
        session_id="session-001",
        sequence=3,
        step_type=LoopStepType.VALIDATE,
        role=RoleName.QA,
        status=HarnessStatus.SUCCEEDED,
        started_at=now,
    )
    decision = LoopDecisionRecord(
        id="decision-001",
        loop_run_id="loop-run-001",
        iteration_id=iteration.id,
        decision=LoopDecisionType.RETRY_IMPLEMENTATION,
        reason="QA validation failed; retrying implementation.",
        created_at=now,
    )
    evidence = EvidenceRef(
        id="evidence-validation",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id=iteration.id,
        kind=EvidenceKind.VALIDATION,
        uri="provider-output://validation",
        summary="Mobile layout still broken below 400px.",
        producer_role=RoleName.QA,
        created_at=now,
    )

    entry = record_decision_memory(
        connection,
        decision=decision,
        iteration=iteration,
        evidence_refs=[evidence],
        scope=str(tmp_path),
    )
    loaded = load_memory_entries(connection, str(tmp_path))

    assert entry is not None
    assert entry.kind == "retry"
    assert entry.source_ref == "decision-001"
    assert entry.role is None
    assert entry.metadata["observed_by_role"] == "qa"
    assert "Mobile layout still broken" in entry.summary
    assert [item.id for item in loaded] == [entry.id]


def test_record_decision_memory_skips_successful_decisions(tmp_path):
    """Verify successful decisions do not create memory entries."""
    now = datetime(2026, 7, 7, 10, 5, tzinfo=UTC)
    connection = _memory_connection(tmp_path)
    iteration = LoopIterationRecord(
        id="iteration-002",
        loop_run_id="loop-run-001",
        session_id="session-001",
        sequence=1,
        step_type=LoopStepType.PLAN,
        role=RoleName.PM,
        status=HarnessStatus.SUCCEEDED,
        started_at=now,
    )
    decision = LoopDecisionRecord(
        id="decision-002",
        loop_run_id="loop-run-001",
        iteration_id=iteration.id,
        decision=LoopDecisionType.CONTINUE,
        reason="plan step completed successfully.",
        created_at=now,
    )

    entry = record_decision_memory(
        connection,
        decision=decision,
        iteration=iteration,
        evidence_refs=[],
        scope=str(tmp_path),
    )

    assert entry is None
    assert load_memory_entries(connection, str(tmp_path)) == []


def test_workflow_pause_records_memory_and_injects_into_context(tmp_path):
    """Verify a paused workflow writes memory that future packages carry."""
    connection = _memory_connection(tmp_path)
    session_id = create_workflow_session(connection, tmp_path)

    run_workflow(connection, session_id, _AlwaysFailValidationProvider())
    entries = load_memory_entries(connection, str(tmp_path))

    assert entries
    assert {entry.kind for entry in entries} <= {"retry", "failure", "pause"}

    loop_run = load_loop_runs_for_session(connection, session_id)[-1]
    package = build_context_package(
        connection,
        session_id=session_id,
        loop_run_id=loop_run.id,
        iteration_id=None,
        role=RoleName.ENGINEER,
        task_id=None,
        project_root=tmp_path,
    )

    assert package.memory_summaries
    assert any("validation" in summary.lower() for summary in package.memory_summaries)


def test_context_package_memory_injection_is_bounded(tmp_path):
    """Verify memory injection respects entry and total size caps."""
    now = datetime(2026, 7, 7, 10, 10, tzinfo=UTC)
    connection = _memory_connection(tmp_path)
    session_id = create_workflow_session(connection, tmp_path)
    loop_run = load_loop_runs_for_session(connection, session_id)[-1]
    for index in range(8):
        insert_memory_entry(
            connection,
            MemoryEntryRecord(
                id=f"memory-{index:03d}",
                scope=str(tmp_path),
                role=RoleName.ENGINEER,
                source_ref=f"decision-{index:03d}",
                summary="x" * 500,
                kind="failure",
                created_at=now,
            ),
        )

    package = build_context_package(
        connection,
        session_id=session_id,
        loop_run_id=loop_run.id,
        iteration_id=None,
        role=RoleName.ENGINEER,
        task_id=None,
        project_root=tmp_path,
    )

    assert len(package.memory_summaries) <= 5
    assert all(len(summary) <= 400 for summary in package.memory_summaries)
    assert sum(len(summary) for summary in package.memory_summaries) <= 1200


def test_shell_memory_command_renders_distilled_lessons(tmp_path):
    """Verify /memory surfaces recorded lessons in the shell."""
    connection = _memory_connection(tmp_path)
    session_id = create_workflow_session(connection, tmp_path)
    run_workflow(connection, session_id, _AlwaysFailValidationProvider())
    connection.close()

    state = ShellState(project_root=tmp_path)
    response = handle_shell_input(state, "/memory")

    assert response.text.startswith("Memory:")
    assert "[" in response.text
    assert "source:" in response.text

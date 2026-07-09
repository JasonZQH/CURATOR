"""Verify SQLite state schema and persistence helpers."""

from datetime import UTC, datetime

from curator.core.enums import (
    EvidenceKind,
    EventType,
    HarnessStatus,
    LoopDecisionType,
    LoopStatus,
    LoopStepType,
    MessageType,
    ProviderBindingStatus,
    ProviderName,
    ProviderProfileStatus,
    RoleName,
    SessionMode,
    StopCondition,
    TaskStatus,
    ProviderRunStatus,
    ProviderSessionStatus,
    QuotaStatus,
    RoleInstanceStatus,
)
from curator.core.paths import build_curator_paths
from curator.core.schema import (
    DoneCriteria,
    EventRecord,
    EvidenceRef,
    GuideRef,
    HarnessRunResult,
    HarnessRunSpec,
    LoopContract,
    LoopDecisionRecord,
    LoopIterationRecord,
    LoopRunRecord,
    LoopTemplate,
    MemoryEntryRecord,
    MessageRecord,
    PMConfirmationOutput,
    ProviderProfileRecord,
    ProviderRunResult,
    ProviderRunRecord,
    ProviderSessionRecord,
    RoleInstanceRecord,
    RoleSelectionRecord,
    RoleProviderBindingRecord,
    QuotaStateRecord,
    SensorRef,
    SessionRecord,
    TaskRecord,
    WorkflowSnapshot,
)
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_evidence_ref,
    insert_event,
    insert_loop_decision,
    insert_loop_iteration,
    insert_loop_run,
    insert_message,
    insert_provider_profile,
    insert_provider_run,
    insert_provider_session,
    insert_role_instance,
    insert_role_selection,
    insert_role_provider_binding,
    insert_memory_entry,
    insert_quota_state,
    insert_session,
    insert_task,
    load_evidence_refs,
    load_events_for_session,
    load_loop_decisions,
    load_loop_iterations,
    load_loop_run,
    load_loop_runs_for_session,
    load_memory_entries,
    load_messages_for_session,
    load_provider_profile,
    load_provider_profiles,
    load_provider_binding_for_role,
    load_role_selections_for_run,
    load_role_provider_bindings,
    load_provider_runs_for_run,
    load_active_provider_session,
    load_quota_state_for_profile,
    load_session,
    load_tasks_for_session,
)


def test_curator_paths_are_project_local(tmp_path):
    """Verify path helpers keep Curator state inside the project."""
    paths = build_curator_paths(tmp_path)

    assert paths.project_root == tmp_path
    assert paths.curator_dir == tmp_path / ".curator"
    assert paths.database == tmp_path / ".curator" / "curator.sqlite"
    assert paths.role_file(RoleName.PM) == (
        tmp_path / ".curator" / "team" / "roles" / "pm" / "role.md"
    )
    assert paths.role_memory_file(RoleName.QA) == tmp_path / ".curator" / "memory" / "roles" / "qa.md"


def test_database_initializes_phase0_tables(tmp_path):
    """Verify Phase 0 tables are created in SQLite."""
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)

    initialize_database(connection)
    rows = connection.execute(
        "select name from sqlite_master where type = 'table' order by name"
    ).fetchall()

    assert [row["name"] for row in rows] == [
        "approval_decisions",
        "approval_requests",
        "assignments",
        "context_packages",
        "discovery_sessions",
        "discussion_turns",
        "events",
        "evidence_refs",
        "goal_drafts",
        "goal_revisions",
        "goal_runs",
        "goals",
        "loop_decisions",
        "loop_iterations",
        "loop_runs",
        "memory_entries",
        "messages",
        "pause_records",
        "provider_profiles",
        "provider_runs",
        "provider_sessions",
        "quota_state",
        "resume_events",
        "role_instances",
        "role_provider_bindings",
        "role_selections",
        "schema_version",
        "sessions",
        "tasks",
        "work_items",
    ]

    sessions_columns = connection.execute("pragma table_info(sessions)").fetchall()
    assert [row["name"] for row in sessions_columns] == [
        "id",
        "project_root",
        "mode",
        "status",
        "created_at",
        "updated_at",
        "metadata_json",
    ]

    loop_iterations_columns = connection.execute("pragma table_info(loop_iterations)").fetchall()
    assert [row["name"] for row in loop_iterations_columns] == [
        "id",
        "loop_run_id",
        "session_id",
        "task_id",
        "sequence",
        "step_type",
        "role",
        "status",
        "started_at",
        "completed_at",
        "metadata_json",
    ]

    role_selections_columns = connection.execute("pragma table_info(role_selections)").fetchall()
    assert [row["name"] for row in role_selections_columns] == [
        "id",
        "session_id",
        "loop_run_id",
        "role_id",
        "display_name",
        "matched_signals_json",
        "score",
        "reason",
        "created_at",
        "metadata_json",
    ]

    goals_columns = connection.execute("pragma table_info(goals)").fetchall()
    assert [row["name"] for row in goals_columns] == [
        "id",
        "source_request",
        "summary",
        "status",
        "current_revision_id",
        "created_at",
        "updated_at",
        "metadata_json",
    ]

    goal_revisions_columns = connection.execute("pragma table_info(goal_revisions)").fetchall()
    assert [row["name"] for row in goal_revisions_columns] == [
        "id",
        "goal_id",
        "revision",
        "status",
        "contract_json",
        "created_at",
        "accepted_at",
        "metadata_json",
    ]

    goal_runs_columns = connection.execute("pragma table_info(goal_runs)").fetchall()
    assert [row["name"] for row in goal_runs_columns] == [
        "id",
        "goal_id",
        "goal_revision_id",
        "session_id",
        "loop_run_id",
        "status",
        "started_at",
        "completed_at",
        "metadata_json",
    ]

    provider_runs_columns = connection.execute("pragma table_info(provider_runs)").fetchall()
    assert [row["name"] for row in provider_runs_columns] == [
        "id",
        "provider",
        "provider_profile_id",
        "provider_session_id",
        "session_id",
        "loop_run_id",
        "iteration_id",
        "role",
        "status",
        "request_json",
        "response_json",
        "error_kind",
        "error_message",
        "created_at",
        "completed_at",
        "metadata_json",
    ]


def test_database_initialization_upgrades_legacy_provider_runs_table(tmp_path):
    """Verify initialization adds provider identity columns to existing ledgers."""
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    connection.execute(
        """
        create table provider_runs (
            id text primary key,
            provider text not null,
            session_id text not null,
            loop_run_id text not null,
            iteration_id text not null,
            role text not null,
            status text not null,
            request_json text not null default '{}',
            response_json text not null default '{}',
            error_kind text,
            error_message text,
            created_at text not null,
            completed_at text,
            metadata_json text not null default '{}'
        )
        """
    )
    connection.commit()

    initialize_database(connection)
    provider_runs_columns = connection.execute("pragma table_info(provider_runs)").fetchall()

    assert "provider_profile_id" in [row["name"] for row in provider_runs_columns]
    assert "provider_session_id" in [row["name"] for row in provider_runs_columns]


def test_session_task_message_event_models_validate_minimal_records():
    """Verify core Pydantic models accept the minimum Phase 0 records."""
    now = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    session = SessionRecord(
        id="session-001",
        project_root="/repo",
        mode=SessionMode.PLAN_FIRST,
        created_at=now,
        updated_at=now,
    )
    task = TaskRecord(
        id="task-001",
        session_id=session.id,
        role=RoleName.ENGINEER,
        status=TaskStatus.QUEUED,
        title="Build state baseline",
        created_at=now,
        updated_at=now,
    )
    message = MessageRecord(
        id="message-001",
        session_id=session.id,
        task_id=task.id,
        role=RoleName.PM,
        type=MessageType.PLAN_READY,
        content="Plan is ready.",
        created_at=now,
    )
    event = EventRecord(
        id="event-001",
        session_id=session.id,
        task_id=task.id,
        type=EventType.TASK_STARTED,
        created_at=now,
    )
    result = ProviderRunResult(
        provider=ProviderName.CODEX,
        role=RoleName.ENGINEER,
        task_id=task.id,
        status=TaskStatus.DONE,
        output="Implementation complete.",
        messages=[message],
        events=[event],
    )
    snapshot = WorkflowSnapshot(
        session=session,
        tasks=[task],
        messages=[message],
        events=[event],
    )

    assert session.mode is SessionMode.PLAN_FIRST
    assert task.status is TaskStatus.QUEUED
    assert message.type is MessageType.PLAN_READY
    assert event.type is EventType.TASK_STARTED
    assert result.provider is ProviderName.CODEX
    assert snapshot.tasks == [task]


def test_loop_models_validate_complete_fake_delivery_ledger():
    """Verify loop models express QA validation followed by PM confirmation."""
    now = datetime(2026, 6, 25, 9, 0, tzinfo=UTC)
    template = LoopTemplate(
        id="coding_delivery_loop",
        name="Coding delivery loop",
        steps=[
            LoopStepType.PLAN,
            LoopStepType.IMPLEMENT,
            LoopStepType.VALIDATE,
            LoopStepType.CONFIRM,
        ],
        done_criteria=[
            DoneCriteria(id="qa-validation-passed", description="Target tests pass."),
            DoneCriteria(id="pm-confirmation-received", description="PM confirms alignment."),
        ],
        guide_refs=[GuideRef(id="pm-role", title="PM role", uri=".curator/team/roles/pm/role.md")],
        sensor_refs=[
            SensorRef(
                id="qa-validation",
                description="QA validation evidence is required before done.",
                required_evidence_kind=EvidenceKind.VALIDATION,
            ),
            SensorRef(
                id="pm-confirmation",
                description="PM confirmation evidence is required before done.",
                required_evidence_kind=EvidenceKind.PM_CONFIRMATION,
            )
        ],
        allowed_decisions=[
            LoopDecisionType.CONTINUE_TO_ENGINEER,
            LoopDecisionType.CONTINUE_TO_QA,
            LoopDecisionType.CONTINUE_TO_PM,
            LoopDecisionType.STOP_DONE,
        ],
        stop_conditions=[StopCondition.DONE_CRITERIA_MET],
    )
    contract = LoopContract(
        id="contract-001",
        session_id="session-001",
        template_id=template.id,
        steps=template.steps,
        done_criteria=template.done_criteria,
        stop_conditions=template.stop_conditions,
    )
    loop_run = LoopRunRecord(
        id="loop-run-001",
        session_id=contract.session_id,
        contract_id=contract.id,
        template_id=template.id,
        status=LoopStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    iteration = LoopIterationRecord(
        id="iteration-pm-confirm",
        loop_run_id=loop_run.id,
        session_id=loop_run.session_id,
        sequence=4,
        step_type=LoopStepType.CONFIRM,
        role=RoleName.PM,
        status=HarnessStatus.SUCCEEDED,
        started_at=now,
    )
    evidence = EvidenceRef(
        id="evidence-pm-confirm",
        session_id=loop_run.session_id,
        loop_run_id=loop_run.id,
        iteration_id=iteration.id,
        kind=EvidenceKind.PM_CONFIRMATION,
        uri="provider-output://pm/confirmation",
        summary="PM confirmed QA results align with the plan.",
        producer_role=RoleName.PM,
        created_at=now,
        content_hash="sha256:fake-pm-confirmation",
    )
    decision = LoopDecisionRecord(
        id="decision-pm-confirm",
        loop_run_id=loop_run.id,
        iteration_id=iteration.id,
        decision=LoopDecisionType.STOP_DONE,
        stop_condition=StopCondition.DONE_CRITERIA_MET,
        reason="PM confirmed QA evidence aligns with PM plan.",
        created_at=now,
    )
    spec = HarnessRunSpec(
        id="harness-pm-confirm",
        session_id=loop_run.session_id,
        loop_run_id=loop_run.id,
        iteration_id=iteration.id,
        role=RoleName.PM,
        step_type=LoopStepType.CONFIRM,
        task_id="task-pm-confirm",
        context_refs=[evidence],
    )
    output = PMConfirmationOutput(
        confirmed=True,
        summary="QA results match the PM plan.",
        aligned_done_criteria=["qa-validation-passed"],
    )
    result = HarnessRunResult(
        spec_id=spec.id,
        status=HarnessStatus.SUCCEEDED,
        role=RoleName.PM,
        step_type=LoopStepType.CONFIRM,
        evidence_refs=[evidence],
        output=output.model_dump(),
    )

    assert contract.steps == [
        LoopStepType.PLAN,
        LoopStepType.IMPLEMENT,
        LoopStepType.VALIDATE,
        LoopStepType.CONFIRM,
    ]
    assert iteration.step_type is LoopStepType.CONFIRM
    assert evidence.kind is EvidenceKind.PM_CONFIRMATION
    assert decision.decision is LoopDecisionType.STOP_DONE
    assert decision.stop_condition is StopCondition.DONE_CRITERIA_MET
    assert output.confirmed is True
    assert result.evidence_refs == [evidence]


def test_loop_repository_round_trips_ledger_records(tmp_path):
    """Verify loop ledger records can be inserted and loaded from SQLite."""
    now = datetime(2026, 6, 25, 10, 0, tzinfo=UTC)
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    initialize_database(connection)
    loop_run = LoopRunRecord(
        id="loop-run-001",
        session_id="session-001",
        contract_id="contract-001",
        template_id="coding_delivery_loop",
        status=LoopStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    iteration = LoopIterationRecord(
        id="iteration-001",
        loop_run_id=loop_run.id,
        session_id=loop_run.session_id,
        task_id="task-pm",
        sequence=1,
        step_type=LoopStepType.PLAN,
        role=RoleName.PM,
        status=HarnessStatus.SUCCEEDED,
        started_at=now,
        completed_at=now,
    )
    evidence = EvidenceRef(
        id="evidence-001",
        session_id=loop_run.session_id,
        loop_run_id=loop_run.id,
        iteration_id=iteration.id,
        kind=EvidenceKind.PLAN,
        uri="provider-output://pm/plan",
        summary="PM plan evidence.",
        producer_role=RoleName.PM,
        created_at=now,
    )
    decision = LoopDecisionRecord(
        id="decision-001",
        loop_run_id=loop_run.id,
        iteration_id=iteration.id,
        decision=LoopDecisionType.CONTINUE_TO_ENGINEER,
        reason="Plan evidence is ready.",
        created_at=now,
    )

    insert_loop_run(connection, loop_run)
    insert_loop_iteration(connection, iteration)
    insert_evidence_ref(connection, evidence)
    insert_loop_decision(connection, decision)

    assert load_loop_run(connection, loop_run.id) == loop_run
    assert load_loop_iterations(connection, loop_run.id) == [iteration]
    assert load_evidence_refs(connection, loop_run.id) == [evidence]
    assert load_loop_decisions(connection, loop_run.id) == [decision]


def test_role_selection_repository_round_trips_selection_ledger(tmp_path):
    """Verify role selection records can be inserted and loaded from SQLite."""
    now = datetime(2026, 6, 25, 11, 0, tzinfo=UTC)
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    initialize_database(connection)
    loop_run = LoopRunRecord(
        id="loop-run-001",
        session_id="session-001",
        contract_id="contract-001",
        template_id="coding_delivery_loop",
        status=LoopStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    selection = RoleSelectionRecord(
        id="selection-001",
        session_id="session-001",
        loop_run_id="loop-run-001",
        role_id="security_reviewer",
        display_name="Security Reviewer",
        matched_signals=["auth", "secret"],
        score=2,
        reason="Selected security_reviewer because it matched: auth, secret.",
        created_at=now,
        metadata={"source": "compiler"},
    )

    insert_loop_run(connection, loop_run)
    insert_role_selection(connection, selection)

    assert load_role_selections_for_run(connection, "loop-run-001") == [selection]


def test_provider_profile_repository_round_trips_runtime_records(tmp_path):
    """Verify provider profiles, bindings, sessions, quota, and runs persist."""
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    initialize_database(connection)
    role_instance = RoleInstanceRecord(
        id="engineer.1",
        role=RoleName.ENGINEER,
        label="Engineer 1",
        status=RoleInstanceStatus.IDLE,
        created_at=now,
        updated_at=now,
    )
    profile = ProviderProfileRecord(
        id="codex-work",
        provider=ProviderName.CODEX,
        label="Codex work",
        credential_ref="env:CODEX_WORK",
        status=ProviderProfileStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        metadata={"owner": "work"},
    )
    binding = RoleProviderBindingRecord(
        id="binding-engineer-1-codex-work",
        role_instance_id="engineer.1",
        provider_profile_id=profile.id,
        status=ProviderBindingStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    provider_session = ProviderSessionRecord(
        id="provider-session-codex-work",
        provider_profile_id=profile.id,
        status=ProviderSessionStatus.ACTIVE,
        started_at=now,
        metadata={"pid": "123"},
    )
    quota = QuotaStateRecord(
        id="quota-codex-work",
        provider_profile_id=profile.id,
        status=QuotaStatus.AVAILABLE,
        reason="manual check",
        observed_at=now,
    )
    loop_run = LoopRunRecord(
        id="loop-run-001",
        session_id="session-001",
        contract_id="contract-001",
        template_id="coding_delivery_loop",
        status=LoopStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    iteration = LoopIterationRecord(
        id="iteration-001",
        loop_run_id=loop_run.id,
        session_id=loop_run.session_id,
        task_id="task-implementation",
        sequence=1,
        step_type=LoopStepType.IMPLEMENT,
        role=RoleName.ENGINEER,
        status=HarnessStatus.SUCCEEDED,
        started_at=now,
        completed_at=now,
    )
    provider_run = ProviderRunRecord(
        id="provider-run-001",
        provider=ProviderName.CODEX,
        provider_profile_id=profile.id,
        provider_session_id=provider_session.id,
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-001",
        role=RoleName.ENGINEER,
        status=ProviderRunStatus.SUCCEEDED,
        request={"context_package_id": "context-001"},
        response={"status": "succeeded"},
        created_at=now,
        completed_at=now,
    )

    insert_role_instance(connection, role_instance)
    insert_provider_profile(connection, profile)
    insert_role_provider_binding(connection, binding)
    insert_provider_session(connection, provider_session)
    insert_quota_state(connection, quota)
    insert_loop_run(connection, loop_run)
    insert_loop_iteration(connection, iteration)
    insert_provider_run(connection, provider_run)

    assert load_provider_profile(connection, profile.id) == profile
    assert load_provider_profiles(connection) == [profile]
    assert load_provider_binding_for_role(connection, "engineer.1") == binding
    assert load_role_provider_bindings(connection) == [binding]
    assert load_active_provider_session(connection, profile.id) == provider_session
    assert load_quota_state_for_profile(connection, profile.id) == quota
    assert load_provider_runs_for_run(connection, "loop-run-001") == [provider_run]


def test_repository_load_helpers_read_session_workflow_records(tmp_path):
    """Verify repository load helpers return session-scoped workflow records."""
    now = datetime(2026, 6, 25, 13, 0, tzinfo=UTC)
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    initialize_database(connection)
    session = SessionRecord(
        id="session-001",
        project_root=tmp_path,
        mode=SessionMode.PLAN_FIRST,
        created_at=now,
        updated_at=now,
    )
    task = TaskRecord(
        id="task-plan",
        session_id=session.id,
        role=RoleName.PM,
        status=TaskStatus.DONE,
        title="Plan fake workflow",
        created_at=now,
        updated_at=now,
    )
    message = MessageRecord(
        id="message-plan",
        session_id=session.id,
        task_id=task.id,
        role=RoleName.PM,
        type=MessageType.PLAN_READY,
        content="Plan evidence is ready.",
        created_at=now,
    )
    event = EventRecord(
        id="event-started",
        session_id=session.id,
        task_id=task.id,
        type=EventType.TASK_STARTED,
        created_at=now,
        payload={"step": "plan"},
    )
    first_loop_run = LoopRunRecord(
        id="loop-run-001",
        session_id=session.id,
        contract_id="contract-001",
        template_id="coding_delivery_loop",
        status=LoopStatus.DONE,
        created_at=now,
        updated_at=now,
    )
    second_loop_run = LoopRunRecord(
        id="loop-run-002",
        session_id=session.id,
        contract_id="contract-002",
        template_id="coding_delivery_loop",
        status=LoopStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )

    insert_session(connection, session)
    insert_task(connection, task)
    insert_message(connection, message)
    insert_event(connection, event)
    insert_loop_run(connection, second_loop_run)
    insert_loop_run(connection, first_loop_run)

    assert load_session(connection, session.id) == session
    assert load_tasks_for_session(connection, session.id) == [task]
    assert load_messages_for_session(connection, session.id) == [message]
    assert load_events_for_session(connection, session.id) == [event]
    assert load_loop_runs_for_session(connection, session.id) == [first_loop_run, second_loop_run]


def test_database_initializes_schema_version_and_indexes(tmp_path):
    """Verify initialization records migrations and creates secondary indexes."""
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)

    initialize_database(connection)

    versions = [
        row["version"]
        for row in connection.execute("select version from schema_version order by version")
    ]
    assert versions == [1, 2]

    index_names = {
        row["name"]
        for row in connection.execute("select name from sqlite_master where type = 'index'")
    }
    assert {
        "idx_memory_entries_scope_role",
        "idx_pause_records_status",
        "idx_evidence_refs_run",
        "idx_provider_runs_run",
        "idx_loop_decisions_run",
        "idx_goal_revisions_goal",
    } <= index_names

    initialize_database(connection)
    repeat_versions = [
        row["version"]
        for row in connection.execute("select version from schema_version order by version")
    ]
    assert repeat_versions == [1, 2]


def test_database_initialization_upgrades_legacy_memory_entries_table(tmp_path):
    """Verify initialization adds learning columns to existing memory ledgers."""
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    connection.execute(
        """
        create table memory_entries (
            id text primary key,
            scope text not null,
            role text,
            source_ref text not null,
            summary text not null,
            created_at text not null,
            metadata_json text not null default '{}'
        )
        """
    )
    connection.commit()

    initialize_database(connection)
    memory_columns = [
        row["name"]
        for row in connection.execute("pragma table_info(memory_entries)").fetchall()
    ]

    assert "kind" in memory_columns
    assert "updated_at" in memory_columns


def test_memory_entries_round_trip_by_scope_and_role(tmp_path):
    """Verify memory entries persist and load with scope and role filters."""
    now = datetime(2026, 7, 7, 9, 0, tzinfo=UTC)
    paths = build_curator_paths(tmp_path)
    connection = connect_database(paths.database)
    initialize_database(connection)

    engineer_entry = MemoryEntryRecord(
        id="memory-001",
        scope="/repo",
        role=RoleName.ENGINEER,
        source_ref="decision-001",
        summary="Validation failed: layout regression on mobile.",
        kind="failure",
        created_at=now,
    )
    shared_entry = MemoryEntryRecord(
        id="memory-002",
        scope="/repo",
        role=None,
        source_ref="decision-002",
        summary="Loop paused for human handoff.",
        kind="pause",
        created_at=now,
    )
    other_scope_entry = MemoryEntryRecord(
        id="memory-003",
        scope="/other",
        role=RoleName.ENGINEER,
        source_ref="decision-003",
        summary="Unrelated project lesson.",
        created_at=now,
    )

    insert_memory_entry(connection, engineer_entry)
    insert_memory_entry(connection, shared_entry)
    insert_memory_entry(connection, other_scope_entry)

    scoped = load_memory_entries(connection, "/repo")
    assert {entry.id for entry in scoped} == {"memory-001", "memory-002"}

    engineer_scoped = load_memory_entries(connection, "/repo", role=RoleName.ENGINEER)
    assert {entry.id for entry in engineer_scoped} == {"memory-001", "memory-002"}

    qa_scoped = load_memory_entries(connection, "/repo", role=RoleName.QA)
    assert {entry.id for entry in qa_scoped} == {"memory-002"}

    limited = load_memory_entries(connection, "/repo", limit=1)
    assert len(limited) == 1

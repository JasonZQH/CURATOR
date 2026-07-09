"""Verify split scheduler modules expose focused helpers."""

from datetime import UTC, datetime

from curator.core.enums import LoopStepType, MessageType, RoleName
from curator.loops.compiler import compile_coding_delivery_plan
from curator.scheduler.ids import scoped_harness_id, scoped_iteration_id, scoped_task_id
from curator.scheduler.session_factory import build_workflow_session_records
from curator.scheduler.step_writer import message_type_for_step


def test_scheduler_ids_are_loop_scoped_and_stable():
    """Verify scheduler id helpers expose loop-scoped record ids."""
    loop_run_id = "loop-run-session-demo-001-abcd1234"

    assert scoped_task_id(loop_run_id, "task-plan") == (
        "loop-run-session-demo-001-abcd1234-task-plan"
    )
    assert scoped_iteration_id(loop_run_id, 2, LoopStepType.IMPLEMENT) == (
        "loop-run-session-demo-001-abcd1234-iteration-002-implement"
    )
    assert scoped_harness_id(loop_run_id, 2, LoopStepType.IMPLEMENT) == (
        "loop-run-session-demo-001-abcd1234-harness-002-implement"
    )


def test_step_writer_maps_loop_steps_to_messages():
    """Verify step writer owns routed message type mapping."""
    assert message_type_for_step(LoopStepType.PLAN) is MessageType.PLAN_READY
    assert message_type_for_step(LoopStepType.IMPLEMENT) is MessageType.IMPLEMENTATION_COMPLETE
    assert message_type_for_step(LoopStepType.VALIDATE) is MessageType.VALIDATION_COMPLETE
    assert message_type_for_step(LoopStepType.CONFIRM) is MessageType.VALIDATION_COMPLETE


def test_session_factory_builds_fake_skeleton_records(tmp_path):
    """Verify session factory builds records without writing the database."""
    now = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
    plan = compile_coding_delivery_plan(
        session_id="session-demo-001",
        contract_id="contract-demo-001",
    )

    skeleton = build_workflow_session_records(
        project_root=tmp_path,
        created_at=now,
        compiled_plan=plan,
    )

    assert skeleton.session.id == "session-demo-001"
    assert skeleton.session.project_root == tmp_path
    assert skeleton.loop_run.session_id == "session-demo-001"
    assert skeleton.loop_run.contract_id == "contract-demo-001"
    assert [task.title for task in skeleton.tasks] == [
        "Plan coding delivery",
        "Implement coding delivery",
        "Validate coding delivery",
        "Confirm coding delivery",
    ]
    assert [task.role for task in skeleton.tasks] == [
        RoleName.PM,
        RoleName.ENGINEER,
        RoleName.QA,
        RoleName.PM,
    ]
    assert skeleton.role_selections == []


def test_session_factory_builds_dynamic_role_selection_records(tmp_path):
    """Verify session factory emits dynamic role selection ledger records."""
    now = datetime(2026, 7, 6, 10, 10, tzinfo=UTC)
    base_plan = compile_coding_delivery_plan(
        session_id="session-demo-001",
        contract_id="contract-demo-001",
    )
    step = base_plan.steps[2].model_copy(
        update={
            "id": "compiled-security-review",
            "role_id": "security_reviewer",
            "role": RoleName.QA,
            "task_id": "task-security-review",
            "task_title": "Security review",
            "sequence": 3,
            "step_type": LoopStepType.VALIDATE,
            "required_evidence_kinds": [],
            "metadata": {
            "role_display_name": "Security Reviewer",
            "selection_reason": "Selected security_reviewer because it matched: auth.",
            "selection_matched_signals": ["auth"],
            "selection_score": 1,
            },
        }
    )
    plan = base_plan.model_copy(update={"steps": [step]})

    skeleton = build_workflow_session_records(
        project_root=tmp_path,
        created_at=now,
        compiled_plan=plan,
    )

    assert len(skeleton.role_selections) == 1
    assert skeleton.role_selections[0].role_id == "security_reviewer"
    assert skeleton.role_selections[0].display_name == "Security Reviewer"
    assert skeleton.role_selections[0].matched_signals == ["auth"]
    assert skeleton.role_selections[0].score == 1
    assert skeleton.role_selections[0].created_at == now

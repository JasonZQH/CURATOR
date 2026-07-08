"""Build stable scheduler record identifiers."""

from uuid import uuid4

from agentctl.core.enums import LoopStepType


def short_uuid() -> str:
    """Return a short random identifier for durable workflow records."""
    return uuid4().hex[:8]


def new_session_id() -> str:
    """Return a unique session id for repeated local workflow runs."""
    return f"session-{short_uuid()}"


def new_loop_run_id(session_id: str) -> str:
    """Return a unique loop run id scoped to one workflow session."""
    return f"loop-run-{session_id}-{short_uuid()}"


def scoped_task_id(loop_run_id: str, task_id: str) -> str:
    """Return a loop-scoped task id for a compiled step task."""
    return f"{loop_run_id}-{task_id}"


def scoped_iteration_id(loop_run_id: str, sequence: int, step_type: LoopStepType) -> str:
    """Return a loop-scoped iteration id for one step attempt."""
    return f"{loop_run_id}-iteration-{sequence:03d}-{step_type.value}"


def scoped_harness_id(loop_run_id: str, sequence: int, step_type: LoopStepType) -> str:
    """Return a loop-scoped harness id for one provider call."""
    return f"{loop_run_id}-harness-{sequence:03d}-{step_type.value}"

"""Verify each attempt has its own durable identity, and the three graphs stay apart.

Retries used to be an in-memory counter over one reused compiled step: a failed attempt
had no identity, so the evidence it produced could not be attributed to it and a resumed
loop could not tell whether an attempt had happened at all.
"""

from datetime import UTC, datetime

from fakes import CodingDeliveryFakeProvider

from curator.core.enums import HarnessStatus, LoopStepType
from curator.core.paths import build_curator_paths
from curator.core.schema import QAValidationOutput
from curator.app import write_init_state
from curator.scheduler.engine import create_workflow_session, run_workflow
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    load_events_for_session,
    load_executions_for_run,
    load_loop_runs_for_session,
    load_task_dependencies_for_session,
)


class _FailValidationOnceProvider(CodingDeliveryFakeProvider):
    """Fail the first validation so the writer is retried exactly once."""

    def __init__(self):
        """Start with the failure pending."""
        self.failed = False

    def run(self, spec):
        """Fail validation the first time it is asked, then behave."""
        if spec.step_type is LoopStepType.VALIDATE and not self.failed:
            self.failed = True
            return QAValidationOutput(
                passed=False, summary="Validation failed once.", checks=["tests"]
            )
        return super().run(spec)


def _run(tmp_path, provider):
    """Run one workflow and return its connection, loop run, and session id."""
    write_init_state(tmp_path)
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    session_id = create_workflow_session(
        connection, tmp_path, created_at=datetime(2026, 8, 17, tzinfo=UTC)
    )
    run_workflow(connection, session_id, provider)
    return connection, load_loop_runs_for_session(connection, session_id)[0], session_id


def test_every_step_records_one_execution_attempt(tmp_path):
    """Verify each step of a clean run leaves exactly one attempt on the ledger."""
    connection, loop_run, _ = _run(tmp_path, CodingDeliveryFakeProvider())
    executions = load_executions_for_run(connection, loop_run.id)
    connection.close()

    assert executions, "a run must leave attempts behind"
    assert all(execution.attempt == 1 for execution in executions)
    assert all(execution.parent_execution_id is None for execution in executions)
    assert all(execution.status is not HarnessStatus.RUNNING for execution in executions)
    assert len({execution.id for execution in executions}) == len(executions)


def test_a_retry_is_a_new_attempt_linked_to_the_one_it_replaces(tmp_path):
    """Verify a retried task gets attempt 2 pointing at attempt 1, not a bumped counter."""
    connection, loop_run, _ = _run(tmp_path, _FailValidationOnceProvider())
    executions = load_executions_for_run(connection, loop_run.id)
    connection.close()

    by_task: dict[str, list] = {}
    for execution in executions:
        by_task.setdefault(execution.task_id, []).append(execution)
    retried = [attempts for attempts in by_task.values() if len(attempts) > 1]

    assert retried, "the failing validation must have caused a retry"
    attempts = sorted(retried[0], key=lambda execution: execution.attempt)
    assert [execution.attempt for execution in attempts] == list(
        range(1, len(attempts) + 1)
    )
    assert attempts[0].parent_execution_id is None
    assert attempts[1].parent_execution_id == attempts[0].id
    # The first attempt survives as its own row rather than being overwritten.
    assert attempts[0].id != attempts[1].id
    assert attempts[0].iteration_id != attempts[1].iteration_id


def test_a_retried_attempt_names_the_event_that_caused_it(tmp_path):
    """Verify the retry's start event cites the previous attempt's completion.

    Event causality is its own column: it answers "why did this happen", which is a
    different question from "which attempt replaced which" and from "which task blocks
    which".
    """
    connection, loop_run, session_id = _run(tmp_path, _FailValidationOnceProvider())
    executions = load_executions_for_run(connection, loop_run.id)
    events = {event.id: event for event in load_events_for_session(connection, session_id)}
    connection.close()

    retries = [
        execution for execution in executions if execution.parent_execution_id is not None
    ]
    assert retries, "the failing validation must have caused a retry"

    caused = [
        event
        for event in events.values()
        if event.causation_id is not None and event.id.endswith("-started")
    ]
    assert caused, "a retried step must record what caused it"
    for event in caused:
        assert event.causation_id in events, "a cause must point at a real event"
        assert events[event.causation_id].id.endswith("-completed")


def test_the_dependency_graph_is_declared_not_inferred_from_order(tmp_path):
    """Verify the plan's ordering is written down as edges a ready queue can read."""
    connection, _, session_id = _run(tmp_path, CodingDeliveryFakeProvider())
    dependencies = load_task_dependencies_for_session(connection, session_id)
    connection.close()

    assert dependencies, "a multi-step plan must declare its edges"
    assert all(
        dependency.task_id != dependency.depends_on_task_id for dependency in dependencies
    ), "no task may depend on itself"
    # A straight-line plan: every task but the first is blocked by exactly one other.
    blocked = [dependency.task_id for dependency in dependencies]
    assert len(blocked) == len(set(blocked))


def test_attempt_numbering_continues_in_a_new_process(tmp_path):
    """Verify the lineage is read off the ledger, not held in the process that started it.

    This is the property that makes a resumed loop continue the same lineage instead of
    opening a second one at attempt 1 — the same failure mode the retry budget had when it
    lived in memory.
    """
    from curator.scheduler.engine import (
        LoopExecutionContext,
        _begin_execution,
        load_compiled_plan_for_run,
    )
    from curator.state.repositories import load_session, load_tasks_for_session

    connection, loop_run, session_id = _run(tmp_path, CodingDeliveryFakeProvider())
    existing = load_executions_for_run(connection, loop_run.id)
    task_id = existing[0].task_id
    connection.close()

    # A new connection stands in for the next process: nothing is carried over in memory.
    reopened = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(reopened)
    plan_step = load_compiled_plan_for_run(loop_run).steps[0]
    ctx = LoopExecutionContext(
        connection=reopened,
        session=load_session(reopened, session_id),
        loop_run=loop_run,
        plan=None,
        provider=None,
        driver=None,
        tasks_by_id={task.id: task for task in load_tasks_for_session(reopened, session_id)},
        role_contracts=None,
        goal_contract=None,
        created_at=datetime(2026, 8, 17, 1, tzinfo=UTC),
    )
    resumed = _begin_execution(
        ctx, task_id, "iteration-resumed", plan_step, datetime(2026, 8, 17, 1, tzinfo=UTC)
    )
    reopened.close()

    prior_for_task = [row for row in existing if row.task_id == task_id]
    assert resumed.attempt == len(prior_for_task) + 1
    assert resumed.parent_execution_id == prior_for_task[-1].id


def test_execution_lineage_never_cycles(tmp_path):
    """Verify following parent links always terminates."""
    connection, loop_run, _ = _run(tmp_path, _FailValidationOnceProvider())
    executions = {
        execution.id: execution for execution in load_executions_for_run(connection, loop_run.id)
    }
    connection.close()

    for execution in executions.values():
        seen = set()
        cursor = execution
        while cursor.parent_execution_id is not None:
            assert cursor.id not in seen, f"lineage cycles at {cursor.id}"
            seen.add(cursor.id)
            cursor = executions[cursor.parent_execution_id]
            assert cursor.attempt < execution.attempt, "a parent must be an earlier attempt"

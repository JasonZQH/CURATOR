"""Persist scheduler step side effects."""

import sqlite3
from datetime import datetime

from curator.core.enums import EventType, LoopStatus, LoopStepType, MessageType, RoleName
from curator.core.schema import EventRecord, LoopRunRecord, MessageRecord
from curator.state.repositories import insert_event, insert_loop_run, insert_message


def message_type_for_step(step_type: LoopStepType) -> MessageType:
    """Return the routed message type emitted after a successful step."""
    message_types = {
        LoopStepType.PLAN: MessageType.PLAN_READY,
        LoopStepType.IMPLEMENT: MessageType.IMPLEMENTATION_COMPLETE,
        LoopStepType.VALIDATE: MessageType.VALIDATION_COMPLETE,
        LoopStepType.REVIEW: MessageType.VALIDATION_COMPLETE,
        LoopStepType.CONFIRM: MessageType.VALIDATION_COMPLETE,
    }
    return message_types[step_type]


def step_completed_event_id(iteration_id: str) -> str:
    """Return the id of the completion event for one iteration.

    Named rather than inlined because the next attempt cites it as its cause, and a
    causal chain that depends on two places agreeing on a string format is not a chain.
    """
    return f"event-{iteration_id}-completed"


def write_step_events(
    connection: sqlite3.Connection,
    session_id: str,
    task_id: str,
    iteration_id: str,
    step_type: LoopStepType,
    created_at: datetime,
    caused_by: str | None = None,
) -> None:
    """Persist start and completion events for one scheduler step.

    `caused_by` is the event that led to this step running — for a retry, the completion
    event of the attempt it replaces. That chain is event causality and nothing else:
    which attempt superseded which is execution lineage, and which task blocks which is
    the dependency graph. Replay follows this one.
    """
    started_id = f"event-{iteration_id}-started"
    insert_event(
        connection,
        EventRecord(
            id=started_id,
            session_id=session_id,
            task_id=task_id,
            type=EventType.TASK_STARTED,
            created_at=created_at,
            payload={"iteration_id": iteration_id, "step": step_type.value},
            causation_id=caused_by,
        ),
    )
    insert_event(
        connection,
        EventRecord(
            id=step_completed_event_id(iteration_id),
            session_id=session_id,
            task_id=task_id,
            type=EventType.TASK_COMPLETED,
            created_at=created_at,
            payload={"iteration_id": iteration_id, "step": step_type.value},
            causation_id=started_id,
        ),
    )


def write_step_message(
    connection: sqlite3.Connection,
    session_id: str,
    task_id: str,
    iteration_id: str,
    step_type: LoopStepType,
    role: RoleName,
    content: str,
    created_at: datetime,
) -> None:
    """Persist one routed message for a successful scheduler step."""
    insert_message(
        connection,
        MessageRecord(
            id=f"message-{iteration_id}",
            session_id=session_id,
            task_id=task_id,
            role=role,
            type=message_type_for_step(step_type),
            content=content,
            created_at=created_at,
        ),
    )


def write_loop_completion(
    connection: sqlite3.Connection,
    loop_run: LoopRunRecord,
    status: LoopStatus,
    completed_at: datetime,
) -> None:
    """Persist the final loop status and completion timestamp."""
    insert_loop_run(
        connection,
        loop_run.model_copy(
            update={
                "status": status,
                "updated_at": completed_at,
                "completed_at": completed_at,
            }
        ),
    )


def write_loop_pause(
    connection: sqlite3.Connection,
    loop_run: LoopRunRecord,
    paused_at: datetime,
) -> None:
    """Persist a paused loop status without a completion timestamp."""
    insert_loop_run(
        connection,
        loop_run.model_copy(
            update={
                "status": LoopStatus.PAUSED,
                "updated_at": paused_at,
                "completed_at": None,
            }
        ),
    )

"""Coordinate durable role-pool work assignment."""

import sqlite3
from datetime import UTC, datetime

from curator.core.enums import (
    AssignmentStatus,
    RoleInstanceStatus,
    RoleName,
    WorkItemKind,
    WorkItemStatus,
)
from curator.core.schema import AssignmentRecord, WorkItemRecord
from curator.state.repositories import (
    insert_assignment,
    insert_role_instance,
    insert_work_item,
    load_idle_role_instances,
    load_pending_work_items,
    load_work_item,
)


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def tick_work_queue(
    connection: sqlite3.Connection, now: datetime | None = None
) -> list[str]:
    """Assign pending work to idle matching role instances."""
    timestamp = now or _now()
    decisions: list[str] = []
    for item in load_pending_work_items(connection):
        idle_roles = load_idle_role_instances(connection, item.required_role.value)
        if not idle_roles:
            decisions.append(f"queued {item.id} waiting for idle {item.required_role.value}")
            continue

        role = idle_roles[0]
        assignment = AssignmentRecord(
            id=f"assignment-{item.id}-{role.id}",
            work_item_id=item.id,
            role_instance_id=role.id,
            session_id=item.session_id,
            goal_id=item.goal_id,
            status=AssignmentStatus.ACTIVE,
            assigned_at=timestamp,
        )
        insert_assignment(connection, assignment)
        insert_work_item(
            connection,
            item.model_copy(
                update={"status": WorkItemStatus.ASSIGNED, "updated_at": timestamp}
            ),
        )
        insert_role_instance(
            connection,
            role.model_copy(
                update={
                    "status": RoleInstanceStatus.BUSY,
                    "current_session_id": item.session_id,
                    "current_goal_id": item.goal_id,
                    "last_used_at": timestamp,
                    "updated_at": timestamp,
                }
            ),
        )
        decisions.append(f"assigned {item.id} to {role.id}")
    return decisions


def enqueue_followup_qa_work(
    connection: sqlite3.Connection, work_item_id: str, now: datetime | None = None
) -> WorkItemRecord:
    """Create a validation work item after implementation completion."""
    timestamp = now or _now()
    source = load_work_item(connection, work_item_id)
    if source is None:
        raise ValueError(f"Unknown work item: {work_item_id}")

    qa_work = WorkItemRecord(
        id=f"{source.id}-qa",
        session_id=source.session_id,
        goal_id=source.goal_id,
        goal_revision_id=source.goal_revision_id,
        kind=WorkItemKind.VALIDATION,
        required_role=RoleName.QA,
        title=f"Validate {source.title}",
        description="Validate the completed implementation handoff.",
        status=WorkItemStatus.PENDING,
        priority=source.priority,
        created_at=timestamp,
        updated_at=timestamp,
        metadata={"source_work_item_id": source.id},
    )
    insert_work_item(connection, qa_work)
    return qa_work

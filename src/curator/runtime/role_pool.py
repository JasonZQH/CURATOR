"""Initialize and maintain durable role pool defaults."""

import sqlite3
from datetime import UTC, datetime

from curator.core.enums import RoleInstanceStatus, RoleName
from curator.core.schema import RoleInstanceRecord
from curator.state.repositories import insert_role_instance, load_role_instances


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def ensure_default_role_pool(
    connection: sqlite3.Connection, now: datetime | None = None
) -> None:
    """Create default PM, Engineer, and QA workers when absent."""
    existing_ids = {role.id for role in load_role_instances(connection)}
    timestamp = now or _now()
    defaults = [
        ("pm.coordinator", RoleName.PM, "PM coordinator", ["routing", "triage"]),
        ("pm.goal-owner.1", RoleName.PM, "PM goal owner 1", ["goal-ownership"]),
        ("pm.research.1", RoleName.PM, "PM research 1", ["research-synthesis"]),
        ("engineer.1", RoleName.ENGINEER, "Engineer 1", ["implementation"]),
        ("engineer.2", RoleName.ENGINEER, "Engineer 2", ["implementation"]),
        ("qa.1", RoleName.QA, "QA 1", ["validation"]),
        ("qa.2", RoleName.QA, "QA 2", ["validation"]),
        # Functional-slot instances carry provider bindings for the
        # single-writer loop: writer edits, reviewer runs fresh-context.
        ("writer.default", RoleName.ENGINEER, "Writer (default)", ["implementation"]),
        ("reviewer.default", RoleName.QA, "Reviewer (default)", ["review"]),
    ]
    for role_id, role_name, label, capabilities in defaults:
        if role_id in existing_ids:
            continue
        insert_role_instance(
            connection,
            RoleInstanceRecord(
                id=role_id,
                role=role_name,
                label=label,
                status=RoleInstanceStatus.IDLE,
                capabilities=capabilities,
                created_at=timestamp,
                updated_at=timestamp,
            ),
        )

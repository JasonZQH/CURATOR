"""Create, save, accept, and load Curator goal contracts."""

import hashlib
import re
import sqlite3
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path

import yaml

from curator.core.enums import EvidenceKind, GoalStatus, RoleName
from curator.core.schema import (
    CuratorPaths,
    GoalAcceptance,
    GoalContract,
    GoalCriterion,
    GoalRevisionRecord,
    GoalVerification,
)
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_goal_identity,
    insert_goal_revision,
    load_goal_revision as load_goal_revision_record,
    next_goal_revision_number,
)


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def _slugify(source_request: str) -> str:
    """Return a stable ASCII slug for a user request."""
    lowered = source_request.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if slug:
        return slug[:48]
    digest = hashlib.sha256(source_request.encode("utf-8")).hexdigest()[:12]
    return digest


def _goal_yaml(goal: GoalContract) -> str:
    """Render one goal contract as editable YAML."""
    return yaml.safe_dump(goal.model_dump(mode="json"), sort_keys=False)


def _unique_goal_id(slug: str, existing_ids: Collection[str]) -> str:
    """Return a goal id that does not overwrite prior goal history."""
    goal_id = f"goal-{slug}"
    if goal_id not in existing_ids:
        return goal_id

    suffix = 2
    while f"{goal_id}-{suffix}" in existing_ids:
        suffix += 1
    return f"{goal_id}-{suffix}"


def propose_goal(source_request: str, existing_ids: Collection[str] = ()) -> GoalContract:
    """Create a deterministic PM goal proposal from natural language."""
    cleaned_request = source_request.strip()
    if not cleaned_request:
        msg = "Goal request cannot be empty."
        raise ValueError(msg)

    return GoalContract(
        id=_unique_goal_id(_slugify(cleaned_request), existing_ids),
        source_request=cleaned_request,
        summary=cleaned_request,
        created_at=_now(),
        done_criteria=[
            GoalCriterion(
                id="qa-validation-passed",
                description="QA validation passes.",
                verifier_role=RoleName.QA,
            ),
            GoalCriterion(
                id="pm-confirmation-received",
                description="PM confirms result matches intent.",
                verifier_role=RoleName.PM,
            ),
        ],
        constraints=["Do not expand scope without user approval."],
        verification=GoalVerification(
            commands=[],
            required_evidence=[
                EvidenceKind.VALIDATION,
                EvidenceKind.PM_CONFIRMATION,
            ],
        ),
        ask_user_when=[
            "scope_unclear",
            "repeated_failure",
            "no_progress_detected",
            "destructive_change_requested",
        ],
    )


def save_goal(paths: CuratorPaths, goal: GoalContract) -> Path:
    """Save one editable goal draft as YAML."""
    goal_path = paths.goal_file(goal.id)
    goal_path.parent.mkdir(parents=True, exist_ok=True)
    goal_path.write_text(_goal_yaml(goal))
    return goal_path


def load_goal(paths: CuratorPaths, goal_id: str) -> GoalContract:
    """Load one editable goal draft from YAML."""
    goal_path = paths.goal_file(goal_id)
    data = yaml.safe_load(goal_path.read_text()) or {}
    return GoalContract.model_validate(data)


def _accepted_goal(goal: GoalContract, accepted_at: datetime) -> GoalContract:
    """Return a user-accepted copy of a draft goal."""
    return goal.model_copy(
        update={
            "status": GoalStatus.ACCEPTED,
            "accepted_by_user": True,
            "accepted_at": accepted_at,
        }
    )


def _write_accepted_revision(
    connection: sqlite3.Connection, goal: GoalContract, accepted_at: datetime
) -> str:
    """Write the accepted goal identity and immutable snapshot."""
    revision_number = next_goal_revision_number(connection, goal.id)
    revision_id = f"{goal.id}-rev-{revision_number:03d}"
    contract = goal.model_dump(mode="json")
    revision = GoalRevisionRecord(
        id=revision_id,
        goal_id=goal.id,
        revision=revision_number,
        status=goal.status,
        contract=contract,
        created_at=accepted_at,
        accepted_at=accepted_at,
    )
    insert_goal_identity(
        connection,
        goal.id,
        goal.source_request,
        goal.summary,
        goal.status.value,
        revision_id,
        (goal.created_at or accepted_at).isoformat(),
        accepted_at.isoformat(),
        goal.metadata,
    )
    insert_goal_revision(connection, revision)
    return revision_id


def accept_goal(paths: CuratorPaths, goal_id: str) -> GoalAcceptance:
    """Accept a draft goal and write its immutable SQLite revision."""
    accepted_at = _now()
    goal = _accepted_goal(load_goal(paths, goal_id), accepted_at)
    connection = connect_database(paths.database)
    try:
        initialize_database(connection)
        revision_id = _write_accepted_revision(connection, goal, accepted_at)
    finally:
        connection.close()

    save_goal(paths, goal)
    return GoalAcceptance(goal=goal, revision_id=revision_id)


def load_goal_revision(
    connection: sqlite3.Connection, revision_id: str
) -> GoalRevisionRecord | None:
    """Load one accepted goal revision from SQLite."""
    return load_goal_revision_record(connection, revision_id)

"""Verify Curator goal contracts, drafts, and accepted ledger snapshots."""

import yaml

from agentctl.core.enums import EvidenceKind, GoalStatus, RoleName
from agentctl.core.paths import build_curator_paths
from agentctl.core.schema import GoalContract, GoalCriterion, GoalVerification
from agentctl.goals.store import accept_goal, load_goal, load_goal_revision, propose_goal, save_goal
from agentctl.state.db import connect_database, initialize_database


def test_goal_contract_models_accept_minimal_goal():
    """Verify the goal contract model captures deterministic PM proposal fields."""
    goal = GoalContract(
        id="goal-login-layout",
        source_request="Fix the login layout.",
        summary="Fix the login layout.",
        done_criteria=[
            GoalCriterion(
                id="qa-validation-passed",
                description="QA validation passes.",
                verifier_role=RoleName.QA,
            )
        ],
        verification=GoalVerification(required_evidence=[EvidenceKind.VALIDATION]),
    )

    assert goal.status is GoalStatus.PROPOSED
    assert goal.accepted_by_user is False
    assert goal.done_criteria[0].verifier_role is RoleName.QA


def test_propose_goal_creates_deterministic_pm_proposal():
    """Verify deterministic PM proposal generation does not pretend provider insight."""
    goal = propose_goal("Fix mobile login layout")

    assert goal.id == "goal-fix-mobile-login-layout"
    assert goal.source_request == "Fix mobile login layout"
    assert goal.summary == "Fix mobile login layout"
    assert goal.status is GoalStatus.PROPOSED
    assert [criterion.id for criterion in goal.done_criteria] == [
        "qa-validation-passed",
        "pm-confirmation-received",
    ]
    assert goal.constraints == ["Do not expand scope without user approval."]


def test_goal_draft_saves_and_loads_yaml_without_touching_sqlite(tmp_path):
    """Verify draft proposals live in YAML until the user accepts them."""
    paths = build_curator_paths(tmp_path)
    goal = propose_goal("Fix mobile login layout")

    save_goal(paths, goal)
    loaded = load_goal(paths, goal.id)

    assert loaded == goal
    assert paths.goal_file(goal.id).exists()
    assert not paths.database.exists()


def test_accept_goal_writes_sqlite_snapshot_without_draft_retroactive_mutation(tmp_path):
    """Verify accepted revisions are immutable even if the draft YAML changes later."""
    paths = build_curator_paths(tmp_path)
    goal = propose_goal("Fix mobile login layout")
    save_goal(paths, goal)

    acceptance = accept_goal(paths, goal.id)
    draft = yaml.safe_load(paths.goal_file(goal.id).read_text())
    draft["summary"] = "User changed the draft later."
    paths.goal_file(goal.id).write_text(yaml.safe_dump(draft, sort_keys=False))

    connection = connect_database(paths.database)
    initialize_database(connection)
    revision = load_goal_revision(connection, acceptance.revision_id)
    connection.close()

    assert acceptance.goal.status is GoalStatus.ACCEPTED
    assert acceptance.goal.accepted_by_user is True
    assert revision is not None
    assert revision.contract["summary"] == "Fix mobile login layout"
    assert load_goal(paths, goal.id).summary == "User changed the draft later."


def test_propose_goal_suffixes_id_on_collision():
    """Verify repeated requests never overwrite prior goal history."""
    existing = {"goal-fix-mobile-login-layout", "goal-fix-mobile-login-layout-2"}

    goal = propose_goal("Fix mobile login layout", existing_ids=existing)

    assert goal.id == "goal-fix-mobile-login-layout-3"
    assert goal.summary == "Fix mobile login layout"

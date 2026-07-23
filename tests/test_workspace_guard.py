"""Verify the clean-tree guard fires only on the loop's first writer dispatch."""

import subprocess
from datetime import UTC, datetime

from fakes import CodingDeliveryFakeProvider

from curator.core.enums import EvidenceKind, LoopDecisionType, RoleName
from curator.core.schema import EvidenceRef
from curator.harness.workspace import stash_workspace
from curator.loops.compiler import compile_single_writer_plan
from curator.scheduler.engine import (
    LoopExecutionState,
    _has_implementation_evidence,
    create_workflow_session,
    run_workflow,
)
from curator.scheduler.resume import resume_workflow_sync
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    load_loop_decisions_for_run,
    load_loop_runs_for_session,
)


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def _evidence(kind: EvidenceKind) -> EvidenceRef:
    return EvidenceRef(
        id=f"evidence-{kind.value}",
        session_id="s",
        loop_run_id="l",
        iteration_id="i",
        kind=kind,
        uri="mock://x",
        summary="x",
        producer_role=RoleName.ENGINEER,
        created_at=datetime(2026, 7, 8, tzinfo=UTC),
    )


def test_has_implementation_evidence_gates_retry_and_resume():
    """Verify the guard is skipped once the loop owns writer output."""
    empty = LoopExecutionState()
    assert _has_implementation_evidence(empty) is False

    after_writer = LoopExecutionState(evidence_refs=[_evidence(EvidenceKind.IMPLEMENTATION)])
    assert _has_implementation_evidence(after_writer) is True

    # Only implementation evidence lifts the guard, not plan/validation alone.
    plan_only = LoopExecutionState(evidence_refs=[_evidence(EvidenceKind.PLAN)])
    assert _has_implementation_evidence(plan_only) is False


def test_first_writer_dispatch_blocks_on_preexisting_dirty_tree(tmp_path):
    """Verify a pre-existing dirty tree still pauses the very first writer run."""
    if _git(tmp_path, "init").returncode != 0:
        import pytest

        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")
    # A pre-existing, non-Curator change the writer did not make.
    (tmp_path / "preexisting.py").write_text("print('user work')\n")

    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    plan = compile_single_writer_plan(
        session_id="session-guard", contract_id="contract-guard"
    )
    session_id = create_workflow_session(connection, tmp_path, compiled_plan=plan)

    run_workflow(connection, session_id, CodingDeliveryFakeProvider(), compiled_plan=plan)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]
    decisions = load_loop_decisions_for_run(connection, loop_run.id)

    assert decisions[-1].decision is LoopDecisionType.HUMAN_HANDOFF
    assert "uncommitted changes" in decisions[-1].reason
    # The dirty pause offers the opt-in stash path via a tailored card.
    assert decisions[-1].metadata.get("pause_resume_mode") == "workspace_dirty"
    assert "clean" in decisions[-1].metadata.get("pause_question", "").lower()
    # The card must name commands the shell actually accepts (no bare /resume).
    assert "/resume stash" in decisions[-1].metadata.get("pause_requested_input", "")
    assert "/resume continue" in decisions[-1].metadata.get("pause_requested_input", "")


def test_stash_workspace_clears_dirty_tree(tmp_path):
    """Verify stash_workspace tucks tracked and untracked changes into a stash."""
    if _git(tmp_path, "init").returncode != 0:
        import pytest

        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "tracked.py").write_text("x = 1\n")
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "tracked.py").write_text("x = 2\n")  # modified tracked file
    (tmp_path / "untracked.py").write_text("y = 3\n")  # new untracked file

    ref = stash_workspace(tmp_path)

    assert ref == "stash@{0}"
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""
    assert "curator: auto-stash" in _git(tmp_path, "stash", "list").stdout
    # A clean tree stashes nothing.
    assert stash_workspace(tmp_path) is None


def test_stash_workspace_never_sweeps_curator_state(tmp_path):
    """Verify the stash excludes .curator/ even when the project does not ignore it."""
    if _git(tmp_path, "init").returncode != 0:
        import pytest

        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")
    (tmp_path / "user.py").write_text("print('user work')\n")  # user change to stash
    (tmp_path / ".curator").mkdir()
    ledger = tmp_path / ".curator" / "curator.sqlite"
    ledger.write_text("LEDGER")  # untracked Curator state, NOT git-ignored here

    ref = stash_workspace(tmp_path)

    assert ref == "stash@{0}"
    # User work is stashed; Curator's own live state survives untouched.
    assert "user.py" not in _git(tmp_path, "status", "--porcelain").stdout
    assert ledger.read_text() == "LEDGER"


def test_resume_stash_clears_dirty_guard(tmp_path):
    """Verify `/resume stash` stashes user work and lets the writer run clean."""
    if _git(tmp_path, "init").returncode != 0:
        import pytest

        pytest.skip("git is not available")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")
    (tmp_path / "preexisting.py").write_text("print('user work')\n")

    connection = connect_database(tmp_path / ".curator" / "curator.sqlite")
    initialize_database(connection)
    plan = compile_single_writer_plan(
        session_id="session-stash", contract_id="contract-stash"
    )
    session_id = create_workflow_session(connection, tmp_path, compiled_plan=plan)

    run_workflow(connection, session_id, CodingDeliveryFakeProvider(), compiled_plan=plan)
    loop_run = load_loop_runs_for_session(connection, session_id)[0]

    resumed = resume_workflow_sync(
        connection, loop_run.id, "stash", CodingDeliveryFakeProvider()
    )

    assert resumed is True
    # The user's change is safely stashed, not lost, and gone from the working tree.
    assert "curator: auto-stash" in _git(tmp_path, "stash", "list").stdout
    assert "preexisting.py" not in _git(tmp_path, "status", "--porcelain").stdout
    # The loop advanced past the dirty guard — no fresh "uncommitted changes" block.
    decisions = load_loop_decisions_for_run(connection, loop_run.id)
    assert "uncommitted changes" not in decisions[-1].reason

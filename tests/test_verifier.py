"""Verify deterministic verification execution and evidence."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from agentctl.core.enums import EvidenceKind, RoleName
from agentctl.harness.verifier import (
    VerificationSpec,
    build_validation_evidence,
    run_verification,
)


def _spec(tmp_path: Path, commands: list[list[str]], timeout: int = 30) -> VerificationSpec:
    """Return one verification spec rooted at the test project."""
    return VerificationSpec(project_root=tmp_path, commands=commands, timeout_seconds=timeout)


def test_run_verification_passes_when_all_commands_succeed(tmp_path):
    """Verify passing commands produce a passed result with per-command data."""
    result = run_verification(
        _spec(
            tmp_path,
            [
                [sys.executable, "-c", "print('ok')"],
                [sys.executable, "-c", "raise SystemExit(0)"],
            ],
        )
    )

    assert result.passed is True
    assert len(result.results) == 2
    assert result.results[0].exit_code == 0
    assert "ok" in result.results[0].stdout_tail


def test_run_verification_fails_and_stops_at_first_failure(tmp_path):
    """Verify a failing command fails the run and skips later commands."""
    result = run_verification(
        _spec(
            tmp_path,
            [
                [sys.executable, "-c", "raise SystemExit(1)"],
                [sys.executable, "-c", "print('never runs')"],
            ],
        )
    )

    assert result.passed is False
    assert len(result.results) == 1
    assert result.results[0].exit_code == 1


def test_run_verification_times_out_hanging_commands(tmp_path):
    """Verify hanging commands are cut off by the per-command timeout."""
    result = run_verification(
        _spec(tmp_path, [[sys.executable, "-c", "import time; time.sleep(30)"]], timeout=1)
    )

    assert result.passed is False
    assert result.results[0].timed_out is True


def test_run_verification_fails_with_note_when_no_commands(tmp_path):
    """Verify absent commands fail with an explicit note, not silence."""
    result = run_verification(_spec(tmp_path, []))

    assert result.passed is False
    assert result.note == "no verification commands configured"


def test_build_validation_evidence_writes_real_report_with_real_hash(tmp_path):
    """Verify verification evidence points at a real artifact with a real digest."""
    spec = _spec(tmp_path, [[sys.executable, "-c", "print('ok')"]])
    result = run_verification(spec)
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)

    evidence = build_validation_evidence(
        result,
        spec,
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-002",
        created_at=now,
    )

    report_path = Path(urlparse(evidence.uri).path)
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["passed"] is True
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert evidence.content_hash == f"sha256:{digest}"
    assert evidence.kind is EvidenceKind.VALIDATION
    assert evidence.producer_role is RoleName.QA
    assert "Verification passed" in evidence.summary

"""Verify Curator diagnostics use cases and terminal renderers."""

from curator.core.paths import build_curator_paths
from curator.app import run_workflow_snapshot, write_init_state
from curator.diagnostics.doctor import inspect_project_health
from curator.diagnostics.status import inspect_project_status
from curator.rendering.terminal import render_doctor_report, render_status_report
from fakes import CodingDeliveryFakeProvider


def test_doctor_reports_missing_state_for_uninitialized_project(tmp_path):
    """Verify doctor reports a clear next step before init has run."""
    report = inspect_project_health(tmp_path)

    assert report.project_root == tmp_path
    assert report.package_version == "0.1.0"
    assert report.state_dir == tmp_path / ".curator"
    assert report.database == tmp_path / ".curator" / "curator.sqlite"
    assert report.initialized is False
    assert report.recommended_next_step == "curator init"
    assert report.checks["state"].status == "missing"
    assert report.checks["database"].status == "missing"


def test_doctor_reports_ready_state_after_init(tmp_path):
    """Verify doctor reports initialized state after Curator state exists."""
    write_init_state(tmp_path)

    report = inspect_project_health(tmp_path)

    assert report.initialized is True
    assert report.mode == "setup"
    assert report.recommended_next_step == "curator provider add claude-code"
    assert report.checks["state"].status == "ok"
    assert report.checks["database"].status == "ok"


def test_status_reports_uninitialized_project_without_creating_state(tmp_path):
    """Verify status is read-only and helpful before init."""
    report = inspect_project_status(tmp_path)

    assert report.project_root == tmp_path
    assert report.initialized is False
    assert report.session_count == 0
    assert report.last_session_id is None
    assert report.last_decision is None
    assert report.next_step == "curator init"
    assert not (tmp_path / ".curator").exists()


def test_status_reports_session_summary_after_demo_run(tmp_path):
    """Verify status summarizes durable loop state after a fake workflow."""
    write_init_state(tmp_path)
    snapshot = run_workflow_snapshot(
        tmp_path,
        CodingDeliveryFakeProvider(),
        session_id="session-demo-001",
    )

    report = inspect_project_status(tmp_path)

    assert report.initialized is True
    assert report.mode == "setup"
    assert report.session_count == 1
    assert report.last_session_id == snapshot.session.id
    assert report.last_decision == "stop_done"
    assert report.last_stop_condition == "done_criteria_met"
    assert report.next_step == "curator provider add claude-code"


def test_status_reports_contract_load_warnings(tmp_path):
    """Verify status includes role contract fallback warnings."""
    write_init_state(tmp_path)
    build_curator_paths(tmp_path).role_contract_file("engineer").write_text(
        "id: engineer\nhandoff_rules: [\n"
    )

    report = inspect_project_status(tmp_path)

    assert len(report.contract_warnings) == 1
    assert report.contract_warnings[0].role_id == "engineer"
    assert report.contract_warnings[0].fallback_used is True
    assert "invalid YAML" in report.contract_warnings[0].message


def test_render_doctor_report_contains_core_checks(tmp_path):
    """Verify doctor rendering stays terminal-friendly and data-driven."""
    report = inspect_project_health(tmp_path)

    output = render_doctor_report(report)

    assert "Curator doctor" in output
    assert f"Project root: {tmp_path}" in output
    assert "State: missing" in output
    assert "Database: missing" in output
    assert "Recommended next step: curator init" in output


def test_render_status_report_contains_session_summary(tmp_path):
    """Verify status rendering includes the current project state."""
    write_init_state(tmp_path)
    run_workflow_snapshot(
        tmp_path,
        CodingDeliveryFakeProvider(),
        session_id="session-demo-001",
    )
    report = inspect_project_status(tmp_path)

    output = render_status_report(report)

    assert "Curator status" in output
    assert "Initialized: yes" in output
    assert "Sessions: 1" in output
    assert "Last session: session-demo-001" in output
    assert "Last decision: stop_done" in output


def test_render_status_report_contains_contract_warnings(tmp_path):
    """Verify status rendering makes contract fallback visible."""
    write_init_state(tmp_path)
    build_curator_paths(tmp_path).role_contract_file("engineer").write_text(
        "id: engineer\nhandoff_rules: [\n"
    )
    report = inspect_project_status(tmp_path)

    output = render_status_report(report)

    assert "Contract warnings:" in output
    assert "engineer" in output
    assert "invalid YAML" in output

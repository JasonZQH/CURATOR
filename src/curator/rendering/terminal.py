"""Render Curator reports as terminal-friendly text."""

from curator.diagnostics.models import DoctorReport, StatusReport
from curator.team.roles import RoleContractValidationResult


def _yes_no(value: bool) -> str:
    """Render a boolean as a compact terminal label."""
    return "yes" if value else "no"


def render_doctor_report(report: DoctorReport) -> str:
    """Render a doctor report as terminal-friendly text."""
    lines = [
        "Curator doctor",
        "",
        f"Python: {report.python_version}",
        f"Package: curator {report.package_version}",
        f"Project root: {report.project_root}",
        f"State: {report.checks['state'].status}",
        f"Database: {report.checks['database'].status}",
        f"Mode: {report.mode}",
    ]
    migrations = report.checks.get("migrations")
    if migrations is not None and migrations.status != "missing":
        lines.append(f"Migrations: {migrations.status} — {migrations.detail}")
    backup = report.checks.get("backup")
    if backup is not None and backup.status == "ok":
        lines.append(f"Backup: {backup.detail}")
    lines.append(f"Recommended next step: {report.recommended_next_step}")
    return "\n".join(lines)


def render_migration_outcome(outcome) -> str:
    """Render what a just-applied migration did, or "" when nothing was migrated.

    Migrating a ledger is not something to do silently: the user should learn that their
    schema moved and where the copy of the old one is, at the moment it happens.
    """
    if outcome is None:
        return ""
    versions = ", ".join(str(version) for version in outcome.applied)
    lines = [f"Migrated ledger: schema v{outcome.from_version} → v{outcome.to_version} ({versions})."]
    if outcome.backup is not None:
        lines.append(f"Previous ledger backed up to {outcome.backup}")
    return "\n".join(lines)


def render_status_report(report: StatusReport) -> str:
    """Render a status report as terminal-friendly text."""
    lines = [
        "Curator status",
        "",
        f"Project: {report.project_root}",
        f"State directory: {report.state_dir}",
        f"Database: {report.database}",
        f"Initialized: {_yes_no(report.initialized)}",
        f"Mode: {report.mode}",
        f"Sessions: {report.session_count}",
        f"Last session: {report.last_session_id or '-'}",
        f"Last decision: {report.last_decision or '-'}",
        f"Next step: {report.next_step}",
    ]
    if report.contract_warnings:
        lines.extend(["", "Contract warnings:"])
        lines.extend(
            (
                f"- {warning.role_id}: {warning.message} "
                f"(fallback: {_yes_no(warning.fallback_used)})"
            )
            for warning in report.contract_warnings
        )
    return "\n".join(lines)


def render_contract_validation_report(report: RoleContractValidationResult) -> str:
    """Render role contract validation as terminal-friendly text."""
    contracts = sorted(report.contracts)
    handoff_count = sum(len(contract.handoff_rules) for contract in report.contracts.values())
    lines = [
        "Curator contract validate",
        "",
        f"Status: {'ok' if report.valid else 'failed'}",
        f"Contracts: {len(report.contracts)}",
        f"Roles: {', '.join(contracts)}",
        f"Handoff rules: {handoff_count}",
    ]
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend(f"- {error.role_id}: {error.message}" for error in report.errors)
    return "\n".join(lines)

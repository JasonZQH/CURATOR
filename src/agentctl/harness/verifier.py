"""Run deterministic verification commands and produce real evidence."""

import hashlib
import json
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agentctl.core.enums import EvidenceKind, RoleName
from agentctl.core.schema import EvidenceRef

DEFAULT_COMMAND_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL_CHARS = 2000


@dataclass(frozen=True)
class VerificationSpec:
    """Describe the commands one verification run must execute."""

    project_root: Path
    commands: list[list[str]] = field(default_factory=list)
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS


@dataclass(frozen=True)
class CommandResult:
    """Describe the observed outcome of one verification command."""

    argv: list[str]
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    duration_seconds: float
    timed_out: bool = False


@dataclass(frozen=True)
class VerificationResult:
    """Describe the outcome of one deterministic verification run."""

    passed: bool
    results: list[CommandResult] = field(default_factory=list)
    note: str | None = None


def _tail(text: str | None) -> str:
    """Return the bounded tail of one command output stream."""
    return (text or "")[-_OUTPUT_TAIL_CHARS:]


def _run_command(argv: list[str], spec: VerificationSpec) -> CommandResult:
    """Execute one verification command without shell interpolation."""
    started = datetime.now(UTC)
    try:
        completed = subprocess.run(
            argv,
            cwd=spec.project_root,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout_tail = _tail(completed.stdout)
        stderr_tail = _tail(completed.stderr)
        timed_out = False
    except subprocess.TimeoutExpired as error:
        exit_code = -1
        stdout_tail = _tail(error.stdout if isinstance(error.stdout, str) else None)
        stderr_tail = _tail(error.stderr if isinstance(error.stderr, str) else None)
        timed_out = True
    except FileNotFoundError as error:
        exit_code = 127
        stdout_tail = ""
        stderr_tail = str(error)
        timed_out = False

    duration = (datetime.now(UTC) - started).total_seconds()
    return CommandResult(
        argv=list(argv),
        exit_code=exit_code,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        duration_seconds=duration,
        timed_out=timed_out,
    )


def run_verification(spec: VerificationSpec) -> VerificationResult:
    """Run verification commands in order, stopping at the first failure."""
    if not spec.commands:
        return VerificationResult(passed=False, note="no verification commands configured")

    results: list[CommandResult] = []
    for argv in spec.commands:
        result = _run_command(list(argv), spec)
        results.append(result)
        if result.exit_code != 0:
            return VerificationResult(passed=False, results=results)

    return VerificationResult(passed=True, results=results)


def discover_verification_commands(project_root: Path | str) -> list[list[str]]:
    """Return conservative verification commands detected from project files."""
    root = Path(project_root)
    commands: list[list[str]] = []
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            config = tomllib.loads(pyproject.read_text())
        except tomllib.TOMLDecodeError:
            config = {}
        if (root / "tests").exists() or config.get("tool", {}).get("pytest"):
            commands.append([sys.executable, "-m", "pytest"])
        if config.get("tool", {}).get("ruff") and (root / "src").exists():
            ruff_targets = ["src"]
            if (root / "tests").exists():
                ruff_targets.append("tests")
            commands.append([sys.executable, "-m", "ruff", "check", *ruff_targets])

    package_json = root / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text())
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if "test" in scripts:
            commands.append(["npm", "test"])
        if "lint" in scripts:
            commands.append(["npm", "run", "lint"])
    return commands


def _verification_summary(result: VerificationResult) -> str:
    """Return the one-line evidence summary for one verification result."""
    if result.passed:
        if result.note:
            return f"Verification passed ({result.note})."
        return f"Verification passed: {len(result.results)} command(s) succeeded."

    if not result.results:
        return f"Verification failed ({result.note or 'no command results'})."

    failing = result.results[-1]
    label = "timed out" if failing.timed_out else f"exited {failing.exit_code}"
    return f"Verification failed: {' '.join(failing.argv)} {label}."


def build_validation_evidence(
    result: VerificationResult,
    spec: VerificationSpec,
    session_id: str,
    loop_run_id: str,
    iteration_id: str,
    created_at: datetime,
) -> EvidenceRef:
    """Persist the verification report and return a real evidence reference."""
    report = {
        "passed": result.passed,
        "note": result.note,
        "commands": [asdict(command) for command in result.results],
    }
    report_bytes = json.dumps(report, sort_keys=True, indent=1).encode("utf-8")
    report_dir = spec.project_root / ".curator" / "artifacts" / loop_run_id / iteration_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "verification.json"
    report_path.write_bytes(report_bytes)
    digest = hashlib.sha256(report_bytes).hexdigest()

    return EvidenceRef(
        id=f"evidence-verify-{iteration_id}",
        session_id=session_id,
        loop_run_id=loop_run_id,
        iteration_id=iteration_id,
        kind=EvidenceKind.VALIDATION,
        uri=report_path.as_uri(),
        summary=_verification_summary(result),
        producer_role=RoleName.QA,
        created_at=created_at,
        content_hash=f"sha256:{digest}",
        metadata={
            "passed": result.passed,
            "command_count": len(result.results),
            "note": result.note,
            "test_commands": [command.argv for command in result.results],
        },
    )

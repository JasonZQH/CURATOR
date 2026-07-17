"""Verify the async subprocess provider driver."""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from curator.core.enums import LoopStepType, ProviderErrorKind, ProviderName, RoleName
from curator.core.schema import HarnessRunSpec
from curator.providers.contracts import (
    ProviderCancelledError,
    ProviderRunRequest,
    ProviderRunResponse,
)
from curator.providers.driver import LegacyProviderDriver, SubprocessDriver
from curator.providers.events import ProviderEvent, ProviderEventKind
from fakes import CodingDeliveryFakeProvider

_FIXTURE = Path(__file__).parent / "fixtures" / "fake_provider_cli.py"


class ScriptedDriver(SubprocessDriver):
    """Drive the scripted fake provider CLI for tests."""

    provider_name = ProviderName.CODEX

    def __init__(self, project_root, scenario: str, timeout_seconds: int = 30) -> None:
        """Bind the driver to one scripted scenario."""
        super().__init__(project_root, timeout_seconds=timeout_seconds)
        self.scenario = scenario

    def build_argv(self, spec, request) -> list[str]:
        """Return the fake CLI invocation for this scenario."""
        return [sys.executable, str(_FIXTURE), "--scenario", self.scenario]

    def parse_event(self, line, provider_run_id, sequence):
        """Map scripted JSONL lines to provider events, dropping garbage."""
        parsed = self.parse_json_line(line)
        if parsed is None:
            return None
        try:
            kind = ProviderEventKind(str(parsed.get("kind")))
        except ValueError:
            return None
        return ProviderEvent(
            kind=kind,
            provider_run_id=provider_run_id,
            sequence=sequence,
            label=str(parsed.get("label", "")),
            payload=parsed,
        )

    def build_response(self, spec, request, events, returncode, stderr_tail):
        """Convert the run outcome into a typed provider response."""
        if returncode != 0:
            return self._failed_response(
                request,
                ProviderErrorKind.PROVIDER_UNAVAILABLE,
                stderr_tail or f"exit {returncode}",
            )
        return ProviderRunResponse.succeeded(
            request,
            ProviderName.CODEX,
            output={"summary": "scripted run complete", "event_count": len(events)},
        )


def _spec() -> HarnessRunSpec:
    """Return one harness spec for driver tests."""
    return HarnessRunSpec(
        id="harness-driver-test",
        session_id="session-001",
        loop_run_id="loop-run-001",
        iteration_id="iteration-001",
        role=RoleName.ENGINEER,
        step_type=LoopStepType.IMPLEMENT,
        task_id="task-001",
    )


def _run(driver: ScriptedDriver, collected: list[ProviderEvent]):
    """Run one driver scenario collecting streamed events."""
    spec = _spec()
    request = ProviderRunRequest.from_harness_spec(spec)
    return asyncio.run(driver.run(spec, request, on_event=collected.append))


def test_subprocess_driver_streams_events_in_order(tmp_path):
    """Verify JSONL lines stream as ordered events framed by lifecycle events."""
    events: list[ProviderEvent] = []

    response = _run(ScriptedDriver(tmp_path, "ok"), events)

    assert response.status.value == "succeeded"
    assert events[0].kind is ProviderEventKind.STARTED
    assert events[-1].kind is ProviderEventKind.COMPLETED
    tool_calls = [event for event in events if event.kind is ProviderEventKind.TOOL_CALL]
    assert [event.label for event in tool_calls] == [
        "Edit src/foo.py",
        "Bash uv run pytest",
    ]
    assert response.output["event_count"] == 3


def test_subprocess_driver_tolerates_malformed_lines(tmp_path):
    """Verify garbage output lines are dropped without crashing the run."""
    events: list[ProviderEvent] = []

    response = _run(ScriptedDriver(tmp_path, "garbage"), events)

    assert response.status.value == "succeeded"
    tool_calls = [event for event in events if event.kind is ProviderEventKind.TOOL_CALL]
    assert [event.label for event in tool_calls] == ["Read README.md"]


def test_subprocess_driver_maps_nonzero_exit_to_failed_response(tmp_path):
    """Verify a failing CLI produces a typed failure with stderr context."""
    events: list[ProviderEvent] = []

    response = _run(ScriptedDriver(tmp_path, "fail"), events)

    assert response.status.value == "failed"
    assert response.error_kind is ProviderErrorKind.PROVIDER_UNAVAILABLE
    assert "boom" in (response.error_message or "")
    assert events[-1].kind is ProviderEventKind.FAILED


def test_subprocess_driver_times_out_and_kills_process(tmp_path):
    """Verify hanging providers are terminated within the timeout budget."""
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        _run(ScriptedDriver(tmp_path, "hang", timeout_seconds=1), [])

    assert time.monotonic() - started < 15


def test_subprocess_driver_cancellation_terminates_process(tmp_path):
    """Verify cancelling the run raises the typed cancellation error."""

    async def _cancel_mid_run() -> None:
        driver = ScriptedDriver(tmp_path, "hang", timeout_seconds=30)
        spec = _spec()
        request = ProviderRunRequest.from_harness_spec(spec)
        task = asyncio.create_task(driver.run(spec, request))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(ProviderCancelledError):
            await task

    started = time.monotonic()
    asyncio.run(_cancel_mid_run())
    assert time.monotonic() - started < 15


def test_subprocess_driver_kills_descendant_process_group(tmp_path):
    """Verify timeout cleanup removes a provider child process as well."""
    with pytest.raises(TimeoutError):
        _run(ScriptedDriver(tmp_path, "spawn_hang", timeout_seconds=1), [])

    child_pid_path = tmp_path / "child.pid"
    assert child_pid_path.exists()
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"descendant process {child_pid} survived process-group cleanup")


def test_legacy_driver_wraps_sync_providers_with_lifecycle_events(tmp_path):
    """Verify sync providers keep working behind the async driver protocol."""
    events: list[ProviderEvent] = []
    spec = _spec()
    request = ProviderRunRequest.from_harness_spec(spec)

    output = asyncio.run(
        LegacyProviderDriver(CodingDeliveryFakeProvider()).run(spec, request, on_event=events.append)
    )

    assert output.summary == "Implementation is complete."
    assert [event.kind for event in events] == [
        ProviderEventKind.STARTED,
        ProviderEventKind.COMPLETED,
    ]

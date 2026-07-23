"""A provider that emits a JSONL line larger than 64 KiB must not crash the run.

asyncio's StreamReader defaults to a 64 KiB line limit, so a single big Codex/Claude
event (a diff, a review that inlines the change) made readline() raise "Separator is not
found, and chunk exceeds the limit" — surfacing as a bogus "Provider invalid output" pause.
"""

import asyncio
import sys

from curator.core.enums import LoopStepType, ProviderName, ProviderRunStatus, RoleName
from curator.core.schema import HarnessRunSpec
from curator.providers.contracts import ProviderRunRequest, ProviderRunResponse
from curator.providers.driver import SubprocessDriver
from curator.providers.events import ProviderEvent, ProviderEventKind

_BIG_LINE_CHARS = 128 * 1024  # comfortably over asyncio's 64 KiB default line limit


class _BigLineDriver(SubprocessDriver):
    """Emit one line far larger than the default 64 KiB stream-reader limit."""

    provider_name = ProviderName.CODEX

    def build_argv(self, spec, request):
        """Spawn a tiny process that writes one oversized line then exits."""
        script = f"import sys; sys.stdout.write('A' * {_BIG_LINE_CHARS} + '\\n')"
        return [sys.executable, "-c", script]

    def build_prompt(self, spec, request):
        """Send no prompt for this fixture."""
        return ""

    def parse_event(self, line, provider_run_id, sequence):
        """Turn each read line into an OUTPUT_CHUNK carrying its length."""
        return ProviderEvent(
            kind=ProviderEventKind.OUTPUT_CHUNK,
            provider_run_id=provider_run_id,
            sequence=sequence,
            payload={"text": line.strip()},
        )

    def build_response(self, spec, request, events, returncode, stderr_tail):
        """Report success once the stream has been fully read."""
        return ProviderRunResponse(
            provider=self.provider_name,
            request_id=request.id,
            status=ProviderRunStatus.SUCCEEDED,
            output={"chunks": len(events)},
        )


def test_subprocess_driver_reads_lines_larger_than_64kib(tmp_path):
    """Verify an oversized provider line streams through instead of failing the run."""
    driver = _BigLineDriver(tmp_path)
    spec = HarnessRunSpec(
        id="harness-1",
        session_id="session-1",
        loop_run_id="loop-1",
        iteration_id="iteration-1",
        role=RoleName.QA,
        step_type=LoopStepType.REVIEW,
        task_id="task-1",
    )
    request = ProviderRunRequest.from_harness_spec(spec)
    events: list[ProviderEvent] = []

    response = asyncio.run(driver.run(spec, request, on_event=events.append))

    assert response.status is ProviderRunStatus.SUCCEEDED
    big = [
        event
        for event in events
        if event.kind is ProviderEventKind.OUTPUT_CHUNK
        and len(event.payload.get("text", "")) >= _BIG_LINE_CHARS
    ]
    assert big, "the 128 KiB provider line should be read without the stream reader crashing"

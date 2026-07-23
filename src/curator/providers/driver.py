"""Drive providers asynchronously with streaming events and cancellation."""

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import signal
from typing import Protocol

from curator.core.enums import ProviderErrorKind, ProviderName
from curator.core.schema import HarnessRunSpec
from curator.providers.base import Provider, RoleOutput
from curator.providers.contracts import (
    ProviderCancelledError,
    ProviderRunRequest,
    ProviderRunResponse,
)
from curator.providers.events import (
    ProviderEvent,
    ProviderEventCallback,
    ProviderEventKind,
)

DEFAULT_RUN_TIMEOUT_SECONDS = 1800
_TERMINATE_GRACE_SECONDS = 5
# asyncio's StreamReader defaults to a 64 KiB line limit; a single provider JSONL event
# (a large diff, tool output, or a review that inlines the change) routinely exceeds that,
# and readline() then raises ValueError("Separator is not found, and chunk exceeds the
# limit"), failing the run as a bogus "invalid output". Give the reader generous headroom
# so a big-but-ordinary line streams through instead of crashing the provider run.
_STREAM_READER_LIMIT = 16 * 1024 * 1024


class ProviderDriver(Protocol):
    """Define the async execution boundary consumed by the scheduler."""

    async def run(
        self,
        spec: HarnessRunSpec,
        request: ProviderRunRequest,
        on_event: ProviderEventCallback | None = None,
    ) -> RoleOutput | ProviderRunResponse:
        """Execute one provider run, streaming events while it works."""
        ...


def _emit(
    on_event: ProviderEventCallback | None,
    kind: ProviderEventKind,
    provider_run_id: str,
    sequence: int,
    label: str = "",
    payload: dict | None = None,
) -> None:
    """Send one event to the callback when a callback is registered."""
    if on_event is None:
        return
    on_event(
        ProviderEvent(
            kind=kind,
            provider_run_id=provider_run_id,
            sequence=sequence,
            label=label,
            payload=payload or {},
        )
    )


class LegacyProviderDriver:
    """Adapt synchronous Provider objects to the async driver protocol."""

    def __init__(self, provider: Provider) -> None:
        """Wrap one synchronous provider."""
        self.provider = provider
        self.provider_name = getattr(provider, "provider_name", ProviderName.CODEX)
        self.provider_profile_id = getattr(provider, "provider_profile_id", None)
        self.provider_session_id = getattr(provider, "provider_session_id", None)
        self.quota_status = getattr(provider, "quota_status", None)

    async def run(
        self,
        spec: HarnessRunSpec,
        request: ProviderRunRequest,
        on_event: ProviderEventCallback | None = None,
    ) -> RoleOutput | ProviderRunResponse:
        """Run the wrapped provider and emit synthetic lifecycle events."""
        _ = request
        _emit(
            on_event,
            ProviderEventKind.STARTED,
            spec.id,
            0,
            label=spec.role.value,
            payload={"provider": self.provider_name.value},
        )
        try:
            output = self.provider.run(spec)
        except Exception:
            _emit(on_event, ProviderEventKind.FAILED, spec.id, 1, label=spec.role.value)
            raise
        _emit(on_event, ProviderEventKind.COMPLETED, spec.id, 1, label=spec.role.value)
        return output


class SubprocessDriver:
    """Run one provider CLI as a streaming JSONL subprocess."""

    provider_name: ProviderName

    def __init__(
        self,
        project_root: Path | str,
        timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
        provider_profile_id: str | None = None,
        provider_session_id: str | None = None,
        quota_status: str | None = None,
    ) -> None:
        """Bind the driver to one project workspace."""
        self.project_root = Path(project_root)
        self.timeout_seconds = timeout_seconds
        self.provider_profile_id = provider_profile_id
        self.provider_session_id = provider_session_id
        self.quota_status = quota_status

    def build_argv(self, spec: HarnessRunSpec, request: ProviderRunRequest) -> list[str]:
        """Return the subprocess argv for one provider run."""
        raise NotImplementedError

    def build_prompt(self, spec: HarnessRunSpec, request: ProviderRunRequest) -> str:
        """Return the prompt to send through stdin instead of process argv."""
        _ = spec, request
        return ""

    def parse_event(
        self, line: str, provider_run_id: str, sequence: int
    ) -> ProviderEvent | None:
        """Map one JSONL output line to a provider event, or drop it."""
        raise NotImplementedError

    def build_response(
        self,
        spec: HarnessRunSpec,
        request: ProviderRunRequest,
        events: list[ProviderEvent],
        returncode: int,
        stderr_tail: str,
    ) -> ProviderRunResponse:
        """Convert the observed run into a typed provider response."""
        raise NotImplementedError

    @staticmethod
    def parse_json_line(line: str) -> dict | None:
        """Parse one JSONL line, tolerating malformed output."""
        stripped = line.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        """Terminate a subprocess, escalating to kill after a grace period."""
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        except TimeoutError:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def run(
        self,
        spec: HarnessRunSpec,
        request: ProviderRunRequest,
        on_event: ProviderEventCallback | None = None,
    ) -> ProviderRunResponse:
        """Spawn the provider CLI and stream its JSONL events."""
        argv = self.build_argv(spec, request)
        prompt = self.build_prompt(spec, request)
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.project_root,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=_STREAM_READER_LIMIT,
        )
        events: list[ProviderEvent] = []
        sequence = 0
        _emit(
            on_event,
            ProviderEventKind.STARTED,
            spec.id,
            sequence,
            label=" ".join(argv[:2]),
            payload={"provider": self.provider_name.value},
        )

        async def _read_stdout() -> None:
            """Read provider stdout lines and emit parsed provider events."""
            nonlocal sequence
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                sequence += 1
                event = self.parse_event(
                    line.decode("utf-8", errors="replace"), spec.id, sequence
                )
                if event is None:
                    continue
                events.append(event)
                if on_event is not None:
                    on_event(event)

        async def _read_stderr() -> bytes:
            """Read all provider stderr bytes after startup."""
            assert process.stderr is not None
            return await process.stderr.read()

        async def _write_stdin() -> None:
            """Feed the prompt to the child and close stdin, tolerating an early exit."""
            if process.stdin is None:
                return
            try:
                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                # The child stopped reading before consuming the prompt; the stdout/stderr
                # readers and the exit code surface the real reason.
                pass
            finally:
                with suppress(BrokenPipeError, ConnectionResetError):
                    process.stdin.close()

        stderr_task: asyncio.Task[bytes] | None = None
        stdout_task: asyncio.Task[None] | None = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                stderr_task = asyncio.create_task(_read_stderr())
                stdout_task = asyncio.create_task(_read_stdout())
                # Feed stdin concurrently with reading stdout so a provider that emits
                # output before consuming its prompt cannot deadlock the drain.
                await _write_stdin()
                await stdout_task
                stderr_bytes = await stderr_task
                returncode = await process.wait()
        except TimeoutError as error:
            await self._terminate(process)
            raise TimeoutError(
                f"Provider run timed out after {self.timeout_seconds}s"
            ) from error
        except asyncio.CancelledError:
            await self._terminate(process)
            raise ProviderCancelledError("Provider run cancelled by user.") from None
        finally:
            if process.returncode is None:
                await self._terminate(process)
            for task in (stdout_task, stderr_task):
                if task is not None and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            with suppress(ProcessLookupError):
                await process.wait()

        stderr_tail = stderr_bytes.decode("utf-8", errors="replace")[-2000:]
        response = self.build_response(spec, request, events, returncode, stderr_tail)
        final_kind = (
            ProviderEventKind.COMPLETED
            if response.error_kind is None
            else ProviderEventKind.FAILED
        )
        _emit(on_event, final_kind, spec.id, sequence + 1)
        return response

    def _failed_response(
        self,
        request: ProviderRunRequest,
        error_kind: ProviderErrorKind,
        error_message: str,
    ) -> ProviderRunResponse:
        """Build a typed failure response for this driver's provider."""
        return ProviderRunResponse.failed(
            request,
            self.provider_name,
            error_kind=error_kind,
            error_message=error_message,
        )


def driver_for_provider(provider: Provider | ProviderDriver) -> ProviderDriver:
    """Return an async driver for either protocol generation."""
    run = getattr(provider, "run", None)
    if run is not None and asyncio.iscoroutinefunction(run):
        return provider  # type: ignore[return-value]
    return LegacyProviderDriver(provider)  # type: ignore[arg-type]

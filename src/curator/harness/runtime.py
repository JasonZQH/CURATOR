"""Run providers behind a narrow harness execution boundary."""

from datetime import UTC, datetime

from curator.core.enums import HarnessStatus, ProviderRunStatus
from curator.core.schema import HarnessRunResult, HarnessRunSpec
from curator.harness.artifacts import build_evidence_ref, expected_step_for_output
from curator.providers.base import Provider
from curator.providers.contracts import ProviderRunRequest, ProviderRunResponse
from curator.providers.driver import ProviderDriver
from curator.providers.events import ProviderEventCallback


def _created_at_or_now(created_at: datetime | None) -> datetime:
    """Return the supplied timestamp or a current UTC timestamp."""
    return created_at or datetime.now(UTC)


def _validate_output_matches_spec(spec: HarnessRunSpec, output: object) -> None:
    """Raise when provider output does not match the requested loop step."""
    expected_step = expected_step_for_output(output)
    if expected_step is not spec.step_type:
        message = (
            "Provider output does not match harness step: "
            f"expected {spec.step_type.value}, got {expected_step.value}"
        )
        raise ValueError(message)


def _result_from_output(
    spec: HarnessRunSpec,
    output: object,
    created_at: datetime | None,
) -> HarnessRunResult:
    """Convert provider output into a validated harness result."""
    if isinstance(output, ProviderRunResponse):
        failed = output.status is ProviderRunStatus.FAILED
        metadata = {"provider_response": output.model_dump(mode="json")}
        if output.error_kind is not None:
            metadata["error_kind"] = output.error_kind.value
        if output.error_message:
            metadata["error_message"] = output.error_message
        return HarnessRunResult(
            spec_id=spec.id,
            status=HarnessStatus.FAILED if failed else HarnessStatus.SUCCEEDED,
            role=spec.role,
            step_type=spec.step_type,
            evidence_refs=output.evidence_refs,
            output=output.output,
            metadata=metadata,
        )

    _validate_output_matches_spec(spec, output)
    evidence = build_evidence_ref(spec, output, _created_at_or_now(created_at))

    return HarnessRunResult(
        spec_id=spec.id,
        status=HarnessStatus.SUCCEEDED,
        role=spec.role,
        step_type=spec.step_type,
        evidence_refs=[evidence],
        output=output.model_dump(),
    )


async def run_harness_async(
    spec: HarnessRunSpec,
    driver: ProviderDriver,
    request: ProviderRunRequest,
    created_at: datetime | None = None,
    on_event: ProviderEventCallback | None = None,
) -> HarnessRunResult:
    """Execute one provider run through an async driver."""
    output = await driver.run(spec, request, on_event=on_event)
    return _result_from_output(spec, output, created_at)


def run_harness(
    spec: HarnessRunSpec,
    provider: Provider,
    created_at: datetime | None = None,
) -> HarnessRunResult:
    """Execute one provider run synchronously (legacy shim for tests)."""
    output = provider.run(spec)
    return _result_from_output(spec, output, created_at)

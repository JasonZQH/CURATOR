"""Shared helpers for real CLI provider adapters."""

from datetime import UTC, datetime
from pathlib import Path

from curator.core.enums import EvidenceKind, ProviderName, ProviderRunStatus
from curator.core.schema import EvidenceRef, HarnessRunSpec
from curator.harness.workspace import WorkspaceBaseline, capture_workspace_evidence
from curator.providers.contracts import ProviderRunRequest, ProviderRunResponse

REVIEWER_SLOT = "reviewer"
_SUMMARY_CHARS = 400


def usage_tokens(payload: dict) -> int | None:
    """Return the total token count from a provider usage block, tolerating shapes.

    Looks for a nested ``usage`` object (top level or under ``message``) and prefers a
    total, else sums input + output. Returns None when no token counts are present, so
    callers can omit the field rather than reporting a fake zero.
    """
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        message = payload.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    for key in ("total_tokens", "total"):
        total = usage.get(key)
        if isinstance(total, int):
            return total
    parts = [
        usage.get(key)
        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens")
        if isinstance(usage.get(key), int)
    ]
    return sum(parts) if parts else None


def build_cli_provider_response(
    spec: HarnessRunSpec,
    request: ProviderRunRequest,
    provider: ProviderName,
    slot: str | None,
    final_text: str,
    baseline: WorkspaceBaseline | None,
    project_root: Path | str,
) -> ProviderRunResponse:
    """Build a typed response with real workspace evidence for one CLI run."""
    now = datetime.now(UTC)
    summary = (final_text or "Provider run completed.")[:_SUMMARY_CHARS]

    if slot == REVIEWER_SLOT:
        evidence = EvidenceRef(
            id=f"evidence-review-{spec.iteration_id}",
            session_id=spec.session_id,
            loop_run_id=spec.loop_run_id,
            iteration_id=spec.iteration_id,
            kind=EvidenceKind.REVIEW,
            uri=f"provider://{provider.value}/review/{spec.id}",
            summary=summary,
            producer_role=spec.role,
            created_at=now,
        )
        return ProviderRunResponse(
            provider=provider,
            request_id=request.id,
            status=ProviderRunStatus.SUCCEEDED,
            output={"summary": summary, "slot": REVIEWER_SLOT},
            evidence_refs=[evidence],
        )

    changed_files: list[str] = []
    content_hash: str | None = None
    uri = f"provider://{provider.value}/implementation/{spec.id}"
    if baseline is not None:
        workspace = capture_workspace_evidence(
            project_root, baseline, spec.loop_run_id, spec.iteration_id
        )
        changed_files = workspace.changed_files
        content_hash = workspace.content_hash
        if workspace.diff_path is not None:
            uri = workspace.diff_path.as_uri()

    evidence = EvidenceRef(
        id=f"evidence-impl-{spec.iteration_id}",
        session_id=spec.session_id,
        loop_run_id=spec.loop_run_id,
        iteration_id=spec.iteration_id,
        kind=EvidenceKind.IMPLEMENTATION,
        uri=uri,
        summary=summary,
        producer_role=spec.role,
        created_at=now,
        content_hash=content_hash,
        metadata={"changed_files": changed_files},
    )
    return ProviderRunResponse(
        provider=provider,
        request_id=request.id,
        status=ProviderRunStatus.SUCCEEDED,
        output={"summary": summary, "changed_files": changed_files},
        evidence_refs=[evidence],
    )

"""Distill loop decisions into durable memory entries."""

import sqlite3

from agentctl.core.enums import EvidenceKind, LoopDecisionType
from agentctl.core.schema import (
    EvidenceRef,
    LoopDecisionRecord,
    LoopIterationRecord,
    MemoryEntryRecord,
)
from agentctl.state.repositories import insert_memory_entry

MAX_MEMORY_SUMMARY_CHARS = 400

_MEMORY_KINDS: dict[LoopDecisionType, str] = {
    LoopDecisionType.RETRY_IMPLEMENTATION: "retry",
    LoopDecisionType.RETRY_STEP: "retry",
    LoopDecisionType.STOP_FAILED: "failure",
    LoopDecisionType.HUMAN_HANDOFF: "pause",
}


def _latest_validation_summary(evidence_refs: list[EvidenceRef]) -> str | None:
    """Return the latest validation evidence summary when present."""
    validations = [
        evidence for evidence in evidence_refs if evidence.kind is EvidenceKind.VALIDATION
    ]
    if not validations:
        return None
    return validations[-1].summary


def _memory_summary(
    decision: LoopDecisionRecord,
    evidence_refs: list[EvidenceRef],
) -> str:
    """Build one bounded human-readable lesson from a decision."""
    summary = f"{decision.decision.value}: {decision.reason}"
    validation_summary = _latest_validation_summary(evidence_refs)
    if validation_summary:
        summary = f"{summary} Evidence: {validation_summary}"
    return summary[:MAX_MEMORY_SUMMARY_CHARS]


def record_decision_memory(
    connection: sqlite3.Connection,
    *,
    decision: LoopDecisionRecord,
    iteration: LoopIterationRecord,
    evidence_refs: list[EvidenceRef],
    scope: str,
) -> MemoryEntryRecord | None:
    """Distill a retry, failure, or pause decision into one memory entry.

    Successful decisions return None; the learning loop only records what went
    wrong so future context packages can carry the lesson forward.
    """
    kind = _MEMORY_KINDS.get(decision.decision)
    if kind is None:
        return None

    # Lessons are stored role-shared: a failed validation is exactly what the
    # next writer attempt needs to see, not something only QA should recall.
    entry = MemoryEntryRecord(
        id=f"memory-{decision.id}",
        scope=scope,
        role=None,
        source_ref=decision.id,
        summary=_memory_summary(decision, evidence_refs),
        kind=kind,
        created_at=decision.created_at,
        metadata={"observed_by_role": iteration.role.value},
    )
    insert_memory_entry(connection, entry)
    return entry

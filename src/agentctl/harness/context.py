"""Build provider context references and rendered prompts for iterations."""

from agentctl.core.enums import LoopStepType
from agentctl.core.schema import EvidenceRef, LoopTemplate
from agentctl.loops.templates import template_requires_evidence
from agentctl.providers.contracts import ProviderRunRequest

_SLOT_INSTRUCTIONS = {
    "writer": (
        "You are the implementation writer. Make the smallest correct change that "
        "satisfies the goal, then report the shell commands that verify it."
    ),
    "reviewer": (
        "You are a fresh-context reviewer. You did not write this change. Review the "
        "goal and the diff for correctness and scope; do not modify files."
    ),
}


def build_context_refs(
    template: LoopTemplate,
    step_type: LoopStepType,
    evidence_refs: list[EvidenceRef],
) -> list[EvidenceRef]:
    """Select prior evidence references required by a template step."""
    return [
        evidence
        for evidence in evidence_refs
        if template_requires_evidence(template, step_type, evidence.kind)
    ]


def render_prompt(request: ProviderRunRequest, slot: str | None = None) -> str:
    """Render a provider prompt body from a typed run request.

    Delivers the goal, constraints, prior evidence summaries, and any distilled
    memory lessons carried in the request metadata — this is the wire that makes
    the context package reach the provider instead of only the ledger.
    """
    lines: list[str] = []
    instruction = _SLOT_INSTRUCTIONS.get(slot or "")
    if instruction:
        lines.append(instruction)
        lines.append("")

    goal_summary = request.goal_snapshot.get("summary") if request.goal_snapshot else None
    lines.append(f"Goal: {goal_summary}" if goal_summary else f"Task: {request.task_id}")

    if request.constraints:
        lines.append("")
        lines.append("Constraints:")
        lines.extend(f"- {constraint}" for constraint in request.constraints)

    if request.evidence_refs:
        lines.append("")
        lines.append("Prior evidence:")
        lines.extend(
            f"- [{evidence.kind.value}] {evidence.summary}" for evidence in request.evidence_refs
        )

    memory = request.metadata.get("memory_summaries")
    if isinstance(memory, list) and memory:
        lines.append("")
        lines.append("Lessons from earlier runs:")
        lines.extend(f"- {str(item)}" for item in memory)

    return "\n".join(lines)

"""Define machine-readable role contracts used by loop compilation."""

from agentctl.core.enums import EvidenceKind, RoleName
from agentctl.core.schema import RoleCollaborator, RoleContract, RoleHandoffRule


def _role_key(role: RoleName | str) -> str:
    """Return the string key used for role contract lookup."""
    return role.value if isinstance(role, RoleName) else role


def default_role_contracts() -> dict[str, RoleContract]:
    """Return the built-in runtime role contracts keyed by role id."""
    return {
        RoleName.PM.value: RoleContract(
            id=RoleName.PM.value,
            display_name="PM",
            responsibilities=[
                "Frame user goals into reviewable work.",
                "Define acceptance criteria before implementation starts.",
                "Confirm QA evidence still matches the original product intent.",
            ],
            when_to_involve=[
                "planning",
                "acceptance-criteria",
                "final-alignment",
            ],
            expected_evidence_kinds=[
                EvidenceKind.PLAN,
                EvidenceKind.PM_CONFIRMATION,
            ],
            forbidden_actions=[
                "edit-source-files",
                "bypass-qa-validation",
            ],
            capability_tags=[
                "planning",
                "acceptance-criteria",
                "alignment-confirmation",
            ],
            collaborators=[
                RoleCollaborator(
                    role_id=RoleName.ENGINEER.value,
                    purpose="Receive approved implementation scope.",
                ),
                RoleCollaborator(
                    role_id=RoleName.QA.value,
                    purpose="Provide validation evidence for final confirmation.",
                ),
            ],
            handoff_rules=[
                RoleHandoffRule(
                    trigger="scope_approved",
                    to_role_id=RoleName.ENGINEER.value,
                    reason="Start implementation after PM scope and acceptance criteria are clear.",
                    required_evidence=[EvidenceKind.PLAN],
                ),
                RoleHandoffRule(
                    trigger="confirmation_accepted",
                    to_role_id="done",
                    reason="Complete the loop after PM confirms QA evidence.",
                    required_evidence=[EvidenceKind.PM_CONFIRMATION],
                ),
            ],
        ),
        RoleName.ENGINEER.value: RoleContract(
            id=RoleName.ENGINEER.value,
            display_name="Engineer",
            responsibilities=[
                "Implement scoped changes from the approved PM plan.",
                "Report changed files, assumptions, and verification commands.",
            ],
            when_to_involve=[
                "implementation",
                "code-change",
                "technical-execution",
            ],
            expected_evidence_kinds=[
                EvidenceKind.IMPLEMENTATION,
            ],
            forbidden_actions=[
                "change-acceptance-criteria",
                "skip-implementation-report",
            ],
            capability_tags=[
                "implementation",
                "code-change",
                "technical-execution",
            ],
            collaborators=[
                RoleCollaborator(
                    role_id=RoleName.QA.value,
                    purpose="Validate implementation evidence.",
                ),
                RoleCollaborator(
                    role_id=RoleName.PM.value,
                    purpose="Clarify scope or acceptance criteria.",
                ),
            ],
            handoff_rules=[
                RoleHandoffRule(
                    trigger="implementation_complete",
                    to_role_id=RoleName.QA.value,
                    reason="Validate implementation before PM confirmation.",
                    required_evidence=[EvidenceKind.IMPLEMENTATION],
                ),
                RoleHandoffRule(
                    trigger="requirements_unclear",
                    to_role_id=RoleName.PM.value,
                    reason="Clarify product scope before continuing implementation.",
                    required_evidence=[],
                ),
            ],
        ),
        RoleName.QA.value: RoleContract(
            id=RoleName.QA.value,
            display_name="QA",
            responsibilities=[
                "Validate implementation evidence against the PM plan.",
                "Report concrete checks before PM confirmation is requested.",
            ],
            when_to_involve=[
                "validation",
                "regression-check",
                "quality-review",
            ],
            expected_evidence_kinds=[
                EvidenceKind.VALIDATION,
            ],
            forbidden_actions=[
                "edit-source-files",
                "change-product-intent",
                "mark-done-without-pm-confirmation",
            ],
            capability_tags=[
                "validation",
                "regression-check",
                "quality-review",
            ],
            collaborators=[
                RoleCollaborator(
                    role_id=RoleName.ENGINEER.value,
                    purpose="Receive failed validation feedback.",
                ),
                RoleCollaborator(
                    role_id=RoleName.PM.value,
                    purpose="Receive passing validation evidence for confirmation.",
                ),
            ],
            handoff_rules=[
                RoleHandoffRule(
                    trigger="validation_failed",
                    to_role_id=RoleName.ENGINEER.value,
                    reason="Return failed validation feedback for implementation repair.",
                    required_evidence=[EvidenceKind.VALIDATION],
                ),
                RoleHandoffRule(
                    trigger="validation_passed",
                    to_role_id=RoleName.PM.value,
                    reason="Send passing validation evidence for final product confirmation.",
                    required_evidence=[EvidenceKind.VALIDATION],
                ),
            ],
        ),
    }


def get_default_role_contract(role: RoleName | str) -> RoleContract:
    """Return one built-in runtime role contract by role id."""
    return default_role_contracts()[_role_key(role)]

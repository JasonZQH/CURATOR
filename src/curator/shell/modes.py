"""Define the approval modes exposed by the Curator shell."""

from enum import Enum


class ApprovalMode(str, Enum):
    """Name one proposal approval policy shown in the footer."""

    PROPOSE = "propose"
    AUTO = "auto"


APPROVAL_MODES: tuple[ApprovalMode, ...] = (ApprovalMode.PROPOSE, ApprovalMode.AUTO)


def mode_for_gate(gate: bool) -> ApprovalMode:
    """Return the display mode that corresponds to a boolean gate setting."""
    return ApprovalMode.PROPOSE if gate else ApprovalMode.AUTO


def next_mode(mode: ApprovalMode) -> ApprovalMode:
    """Return the next approval mode in the stable keyboard cycle."""
    index = APPROVAL_MODES.index(mode)
    return APPROVAL_MODES[(index + 1) % len(APPROVAL_MODES)]

"""Verify runtime role contracts used by the loop compiler."""

import pytest
from pydantic import ValidationError

from curator.core.enums import EvidenceKind, RoleName
from curator.core.schema import RoleCollaborator, RoleContract, RoleHandoffRule
from curator.roles.registry import default_role_contracts, get_default_role_contract


def test_default_role_contracts_express_routing_and_evidence_expectations():
    """Verify default roles expose machine-readable runtime contract fields."""
    contracts = default_role_contracts()

    assert set(contracts) == {"pm", "engineer", "qa"}
    assert contracts["pm"].id == "pm"
    assert "planning" in contracts["pm"].capability_tags
    assert "acceptance-criteria" in contracts["pm"].when_to_involve
    assert EvidenceKind.PLAN in contracts["pm"].expected_evidence_kinds
    assert EvidenceKind.PM_CONFIRMATION in contracts["pm"].expected_evidence_kinds
    assert "edit-source-files" in contracts["pm"].forbidden_actions
    assert "implementation" in contracts["engineer"].capability_tags
    assert EvidenceKind.IMPLEMENTATION in (
        contracts["engineer"].expected_evidence_kinds
    )
    assert "validation" in contracts["qa"].capability_tags
    assert EvidenceKind.VALIDATION in contracts["qa"].expected_evidence_kinds


def test_default_role_contracts_express_collaboration_and_handoff_rules():
    """Verify built-in roles describe collaborator-aware routing contracts."""
    contracts = default_role_contracts()

    engineer = contracts["engineer"]
    assert RoleCollaborator(role_id="qa", purpose="Validate implementation evidence.") in (
        engineer.collaborators
    )
    assert RoleHandoffRule(
        trigger="implementation_complete",
        to_role_id="qa",
        reason="Validate implementation before PM confirmation.",
        required_evidence=[EvidenceKind.IMPLEMENTATION],
    ) in engineer.handoff_rules

    qa = contracts["qa"]
    assert RoleCollaborator(role_id="engineer", purpose="Receive failed validation feedback.") in (
        qa.collaborators
    )
    assert RoleHandoffRule(
        trigger="validation_failed",
        to_role_id="engineer",
        reason="Return failed validation feedback for implementation repair.",
        required_evidence=[EvidenceKind.VALIDATION],
    ) in qa.handoff_rules
    assert RoleHandoffRule(
        trigger="validation_passed",
        to_role_id="pm",
        reason="Send passing validation evidence for final product confirmation.",
        required_evidence=[EvidenceKind.VALIDATION],
    ) in qa.handoff_rules


def test_get_default_role_contract_returns_one_contract_by_role():
    """Verify role lookup returns the contract used by compiler decisions."""
    contract = get_default_role_contract(RoleName.QA)

    assert contract.id == "qa"
    assert contract.display_name == "QA"


def test_role_contract_accepts_user_defined_role_ids():
    """Verify role contracts are not limited to built-in Phase 0 role enums."""
    contract = RoleContract(
        id="security_reviewer",
        display_name="Security Reviewer",
        responsibilities=["Review auth, token, secret, and permission boundaries."],
        when_to_involve=["auth", "secret", "permission"],
        expected_evidence_kinds=[EvidenceKind.ARTIFACT],
        forbidden_actions=["edit-product-scope"],
        capability_tags=["security-review", "auth", "secrets"],
    )

    assert contract.id == "security_reviewer"
    assert "security-review" in contract.capability_tags


def test_handoff_rule_rejects_missing_reason():
    """Verify malformed handoff rules are rejected before routing consumes them."""
    with pytest.raises(ValidationError, match="reason"):
        RoleHandoffRule.model_validate(
            {
                "trigger": "implementation_complete",
                "to_role_id": "qa",
                "required_evidence": ["implementation"],
            }
        )

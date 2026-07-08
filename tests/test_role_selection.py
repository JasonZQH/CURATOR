"""Verify deterministic role candidate selection from role contracts."""

from agentctl.core.enums import EvidenceKind
from agentctl.core.schema import RoleContract
from agentctl.roles.registry import default_role_contracts
from agentctl.roles.selection import select_role_candidates


def test_select_role_candidates_matches_default_role_contract_signals():
    """Verify built-in roles are selected from capability and involvement signals."""
    contracts = default_role_contracts()

    planning = select_role_candidates(contracts, ["acceptance-criteria"])
    implementation = select_role_candidates(contracts, ["code-change"])
    validation = select_role_candidates(contracts, ["regression-check"])

    assert [selection.role_id for selection in planning] == ["pm"]
    assert planning[0].matched_signals == ["acceptance-criteria"]
    assert [selection.role_id for selection in implementation] == ["engineer"]
    assert [selection.role_id for selection in validation] == ["qa"]


def test_select_role_candidates_supports_user_defined_role_contracts():
    """Verify custom role contracts can be selected without editing workflows."""
    contracts = default_role_contracts()
    contracts["security_reviewer"] = RoleContract(
        id="security_reviewer",
        display_name="Security Reviewer",
        responsibilities=["Review auth, token, secret, and permission boundaries."],
        when_to_involve=["auth", "secret", "permission"],
        expected_evidence_kinds=[EvidenceKind.ARTIFACT],
        forbidden_actions=["edit-product-scope"],
        capability_tags=["security-review", "auth", "secrets"],
    )

    selections = select_role_candidates(contracts, ["auth", "secret"])

    assert [selection.role_id for selection in selections] == ["security_reviewer"]
    assert selections[0].display_name == "Security Reviewer"
    assert selections[0].matched_signals == ["auth", "secret"]
    assert selections[0].score == 2
    assert "auth, secret" in selections[0].reason


def test_select_role_candidates_ignores_explicitly_excluded_roles():
    """Verify selection can avoid roles already anchored by the core loop."""
    selections = select_role_candidates(
        default_role_contracts(),
        ["planning", "code-change"],
        excluded_role_ids={"pm"},
    )

    assert [selection.role_id for selection in selections] == ["engineer"]

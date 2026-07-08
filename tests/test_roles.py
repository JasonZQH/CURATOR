"""Verify default role contract generation."""

import yaml

from agentctl.core.enums import RoleName
from agentctl.core.paths import build_curator_paths
from agentctl.team.roles import (
    default_role_contract_documents,
    default_role_documents,
    load_role_contracts,
    validate_role_contracts,
    write_default_roles,
)


def test_default_roles_are_html_documents_with_required_sections():
    """Verify default role documents follow the Curator document contract."""
    roles = default_role_documents()

    assert set(roles) == {RoleName.PM, RoleName.ENGINEER, RoleName.QA}
    for role, content in roles.items():
        assert f"<h1>{role.value} role</h1>" in content
        assert "<h2>What</h2>" in content
        assert "<h2>How</h2>" in content
        assert "<h2>Why</h2>" in content
        assert "<h2>Future improvements/considerations/trade-offs</h2>" in content


def test_default_role_documents_include_collaboration_sections():
    """Verify default role documents expose collaborators and handoff rules."""
    roles = default_role_documents()
    engineer_doc = roles[RoleName.ENGINEER]
    qa_doc = roles[RoleName.QA]

    assert "<h2>Collaborators</h2>" in engineer_doc
    assert "<li><strong>qa</strong>: Validate implementation evidence.</li>" in engineer_doc
    assert "<h2>Handoff rules</h2>" in engineer_doc
    assert (
        "<li><strong>implementation_complete</strong> -> <strong>qa</strong>: "
        "Validate implementation before PM confirmation. "
        "Required evidence: implementation.</li>"
    ) in engineer_doc
    assert (
        "<li><strong>validation_failed</strong> -> <strong>engineer</strong>: "
        "Return failed validation feedback for implementation repair. "
        "Required evidence: validation.</li>"
    ) in qa_doc


def test_default_role_contract_documents_are_editable_yaml():
    """Verify default role contracts expose only high-value editable fields."""
    contracts = default_role_contract_documents()
    engineer = yaml.safe_load(contracts[RoleName.ENGINEER])

    assert set(engineer) == {"id", "collaborators", "handoff_rules"}
    assert engineer["handoff_rules"][0]["trigger"] == "implementation_complete"
    assert engineer["handoff_rules"][0]["to_role_id"] == "qa"
    assert engineer["handoff_rules"][0]["required_evidence"] == ["implementation"]


def test_write_default_roles_creates_role_files_without_overwriting(tmp_path):
    """Verify default role files are created without replacing existing files."""
    paths = build_curator_paths(tmp_path)
    existing_role = paths.role_file(RoleName.PM)
    existing_contract = paths.role_contract_file(RoleName.PM)
    existing_role.parent.mkdir(parents=True)
    existing_role.write_text("<h1>custom pm role</h1>\n")
    existing_contract.write_text("id: pm\ncustom: true\n")

    written = write_default_roles(paths)

    assert paths.role_file(RoleName.ENGINEER) in written
    assert paths.role_file(RoleName.QA) in written
    assert paths.role_contract_file(RoleName.ENGINEER) in written
    assert paths.role_contract_file(RoleName.QA) in written
    assert paths.role_file(RoleName.PM) not in written
    assert paths.role_contract_file(RoleName.PM) not in written
    assert existing_role.read_text() == "<h1>custom pm role</h1>\n"
    assert existing_contract.read_text() == "id: pm\ncustom: true\n"


def test_load_role_contracts_reads_user_edited_contract_yaml(tmp_path):
    """Verify role contract loading respects user-edited handoff rules."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    engineer_contract = paths.role_contract_file(RoleName.ENGINEER)
    parsed = yaml.safe_load(engineer_contract.read_text())
    parsed["handoff_rules"][0]["reason"] = "Custom project QA gate."
    engineer_contract.write_text(yaml.safe_dump(parsed, sort_keys=False))

    result = load_role_contracts(paths)

    assert result.warnings == []
    assert result.contracts["engineer"].handoff_rules[0].reason == "Custom project QA gate."
    assert result.contracts["engineer"].display_name == "Engineer"


def test_load_role_contracts_merges_partial_contract_yaml(tmp_path):
    """Verify partial contract YAML inherits built-in role fields."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    paths.role_contract_file(RoleName.ENGINEER).write_text(
        yaml.safe_dump(
            {
                "id": "engineer",
                "handoff_rules": [
                    {
                        "trigger": "implementation_complete",
                        "to_role_id": "qa",
                        "reason": "Run a project QA gate.",
                        "required_evidence": ["implementation"],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    result = load_role_contracts(paths)

    assert result.warnings == []
    assert result.contracts["engineer"].display_name == "Engineer"
    assert result.contracts["engineer"].responsibilities
    assert result.contracts["engineer"].handoff_rules[0].reason == "Run a project QA gate."


def test_load_role_contracts_falls_back_for_invalid_yaml(tmp_path):
    """Verify malformed YAML falls back to built-in contracts with warnings."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    paths.role_contract_file(RoleName.ENGINEER).write_text("id: engineer\nhandoff_rules: [\n")

    result = load_role_contracts(paths)

    assert result.contracts["engineer"].handoff_rules[0].reason == (
        "Validate implementation before PM confirmation."
    )
    assert len(result.warnings) == 1
    assert result.warnings[0].role_id == "engineer"
    assert result.warnings[0].fallback_used is True
    assert "invalid YAML" in result.warnings[0].message


def test_load_role_contracts_falls_back_for_invalid_schema(tmp_path):
    """Verify schema-invalid YAML falls back to built-in contracts with warnings."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    paths.role_contract_file(RoleName.QA).write_text(
        yaml.safe_dump(
            {
                "id": "qa",
                "handoff_rules": [
                    {
                        "trigger": "validation_passed",
                        "to_role_id": "pm",
                        "required_evidence": ["validation"],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    result = load_role_contracts(paths)

    assert result.contracts["qa"].handoff_rules[1].reason == (
        "Send passing validation evidence for final product confirmation."
    )
    assert len(result.warnings) == 1
    assert result.warnings[0].role_id == "qa"
    assert "schema validation failed" in result.warnings[0].message


def test_validate_role_contracts_reports_invalid_yaml_without_fallback_success(tmp_path):
    """Verify strict validation reports broken YAML as an error."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    paths.role_contract_file(RoleName.ENGINEER).write_text("id: engineer\nhandoff_rules: [\n")

    result = validate_role_contracts(paths)

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].role_id == "engineer"
    assert "invalid YAML" in result.errors[0].message


def test_validate_role_contracts_reports_unknown_handoff_targets(tmp_path):
    """Verify strict validation catches handoff rules pointing nowhere."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    parsed = yaml.safe_load(paths.role_contract_file(RoleName.ENGINEER).read_text())
    parsed["handoff_rules"][0]["to_role_id"] = "security"
    paths.role_contract_file(RoleName.ENGINEER).write_text(yaml.safe_dump(parsed, sort_keys=False))

    result = validate_role_contracts(paths)

    assert result.valid is False
    assert result.errors[0].role_id == "engineer"
    assert "unknown handoff target" in result.errors[0].message


def test_validate_role_contracts_accepts_partial_contract_yaml(tmp_path):
    """Verify strict validation accepts valid partial editable contracts."""
    paths = build_curator_paths(tmp_path)
    write_default_roles(paths)
    paths.role_contract_file(RoleName.ENGINEER).write_text(
        yaml.safe_dump(
            {
                "id": "engineer",
                "handoff_rules": [
                    {
                        "trigger": "implementation_complete",
                        "to_role_id": "qa",
                        "reason": "Run QA.",
                        "required_evidence": ["implementation"],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    result = validate_role_contracts(paths)

    assert result.valid is True
    assert result.errors == []
    assert result.contracts["engineer"].handoff_rules[0].reason == "Run QA."

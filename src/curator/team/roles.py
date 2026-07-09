"""Generate default PM, Engineer, and QA role contracts."""

from html import escape
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml import YAMLError

from curator.core.enums import RoleName
from curator.core.models.base import CuratorModel
from curator.core.schema import CuratorPaths, RoleContract, RoleHandoffRule
from curator.roles.registry import default_role_contracts


class RoleContractLoadWarning(CuratorModel):
    """Describe a recoverable role contract loading problem."""

    path: Path
    role_id: str
    message: str
    fallback_used: bool


class RoleContractLoadResult(CuratorModel):
    """Describe role contracts loaded for runtime use and any warnings."""

    contracts: dict[str, RoleContract]
    warnings: list[RoleContractLoadWarning]


class RoleContractValidationIssue(CuratorModel):
    """Describe one strict role contract validation problem."""

    path: Path
    role_id: str
    message: str


class RoleContractValidationResult(CuratorModel):
    """Describe strict validation status for editable role contracts."""

    valid: bool
    contracts: dict[str, RoleContract]
    errors: list[RoleContractValidationIssue]


def _render_list(items: list[str]) -> str:
    """Render escaped strings as HTML list items."""
    if not items:
        return "<p>None.</p>\n"

    lines = ["<ul>"]
    lines.extend(f"<li>{escape(item)}</li>" for item in items)
    lines.append("</ul>")
    return "\n".join(lines) + "\n"


def _render_collaborators(contract: RoleContract) -> str:
    """Render a role contract's collaborators as HTML list content."""
    if not contract.collaborators:
        return "<p>None.</p>\n"

    lines = ["<ul>"]
    lines.extend(
        (
            f"<li><strong>{escape(collaborator.role_id)}</strong>: "
            f"{escape(collaborator.purpose)}</li>"
        )
        for collaborator in contract.collaborators
    )
    lines.append("</ul>")
    return "\n".join(lines) + "\n"


def _required_evidence_label(rule: RoleHandoffRule) -> str:
    """Return a human-readable required evidence label for a handoff rule."""
    if not rule.required_evidence:
        return "none"

    return ", ".join(evidence.value for evidence in rule.required_evidence)


def _render_handoff_rules(contract: RoleContract) -> str:
    """Render a role contract's handoff rules as HTML list content."""
    if not contract.handoff_rules:
        return "<p>None.</p>\n"

    lines = ["<ul>"]
    lines.extend(
        (
            f"<li><strong>{escape(rule.trigger)}</strong> -> "
            f"<strong>{escape(rule.to_role_id)}</strong>: {escape(rule.reason)} "
            f"Required evidence: {escape(_required_evidence_label(rule))}.</li>"
        )
        for rule in contract.handoff_rules
    )
    lines.append("</ul>")
    return "\n".join(lines) + "\n"


def _role_document(contract: RoleContract) -> str:
    """Render one default role document in the required HTML shape."""
    title = f"{contract.id} role"
    summary = " ".join(contract.responsibilities)
    workflow = "Involve this role for: " + ", ".join(contract.when_to_involve) + "."
    return (
        f"<h1>{title}</h1>\n"
        "<section>\n"
        "<h2>What</h2>\n"
        f"<p>{escape(summary)}</p>\n"
        "</section>\n"
        "<section>\n"
        "<h2>How</h2>\n"
        f"<p>{escape(workflow)}</p>\n"
        "<h3>Responsibilities</h3>\n"
        f"{_render_list(contract.responsibilities)}"
        "<h3>Forbidden actions</h3>\n"
        f"{_render_list(contract.forbidden_actions)}"
        "</section>\n"
        "<section>\n"
        "<h2>Collaborators</h2>\n"
        f"{_render_collaborators(contract)}"
        "</section>\n"
        "<section>\n"
        "<h2>Handoff rules</h2>\n"
        f"{_render_handoff_rules(contract)}"
        "</section>\n"
        "<section>\n"
        "<h2>Why</h2>\n"
        "<p>This role keeps Curator work reviewable, bounded, and easy to route.</p>\n"
        "</section>\n"
        "<section>\n"
        "<h2>Future improvements/considerations/trade-offs</h2>\n"
        "<p>Refine this contract as project conventions and trust boundaries become clearer.</p>\n"
        "</section>\n"
    )


def default_role_documents() -> dict[RoleName, str]:
    """Return the default Phase 0 role documents keyed by role."""
    contracts = default_role_contracts()
    return {
        RoleName.PM: _role_document(contracts[RoleName.PM.value]),
        RoleName.ENGINEER: _role_document(contracts[RoleName.ENGINEER.value]),
        RoleName.QA: _role_document(contracts[RoleName.QA.value]),
    }


def _role_contract_yaml(contract: RoleContract) -> str:
    """Render one role contract as editable YAML."""
    editable = {
        "id": contract.id,
        "collaborators": [
            collaborator.model_dump(mode="json", exclude={"metadata"})
            for collaborator in contract.collaborators
        ],
        "handoff_rules": [
            rule.model_dump(mode="json", exclude={"metadata"})
            for rule in contract.handoff_rules
        ],
    }
    return yaml.safe_dump(editable, sort_keys=False)


def default_role_contract_documents() -> dict[RoleName, str]:
    """Return the default editable role contract YAML keyed by role."""
    contracts = default_role_contracts()
    return {
        RoleName.PM: _role_contract_yaml(contracts[RoleName.PM.value]),
        RoleName.ENGINEER: _role_contract_yaml(contracts[RoleName.ENGINEER.value]),
        RoleName.QA: _role_contract_yaml(contracts[RoleName.QA.value]),
    }


def _warning(
    path: Path,
    role_id: str,
    message: str,
) -> RoleContractLoadWarning:
    """Return one runtime-safe contract loading warning."""
    return RoleContractLoadWarning(
        path=path,
        role_id=role_id,
        message=message,
        fallback_used=True,
    )


def _validation_issue(
    path: Path,
    role_id: str,
    message: str,
) -> RoleContractValidationIssue:
    """Return one strict role contract validation issue."""
    return RoleContractValidationIssue(path=path, role_id=role_id, message=message)


def _merge_contract_overlay(
    default_contract: RoleContract,
    overlay: dict[str, Any],
) -> dict[str, Any]:
    """Merge user-editable contract fields into a built-in role contract."""
    merged = default_contract.model_dump(mode="json")
    merged.update(overlay)
    merged["id"] = overlay.get("id", default_contract.id)
    return merged


def _load_contract_overlay(path: Path) -> dict[str, Any]:
    """Load a YAML contract overlay as a dictionary."""
    loaded = yaml.safe_load(path.read_text()) or {}
    if not isinstance(loaded, dict):
        msg = "contract YAML must be a mapping."
        raise ValueError(msg)
    return loaded


def load_role_contracts(paths: CuratorPaths) -> RoleContractLoadResult:
    """Load editable role contracts with fallback warnings for invalid files."""
    contracts = default_role_contracts()
    warnings: list[RoleContractLoadWarning] = []
    for role in RoleName:
        role_id = role.value
        path = paths.role_contract_file(role)
        if not path.exists():
            continue

        default_contract = contracts[role_id]
        try:
            overlay = _load_contract_overlay(path)
            merged = _merge_contract_overlay(default_contract, overlay)
            contract = RoleContract.model_validate(merged)
        except YAMLError as error:
            warnings.append(
                _warning(path, role_id, f"invalid YAML; using built-in {role_id} contract: {error}")
            )
            continue
        except ValidationError as error:
            warnings.append(
                _warning(
                    path,
                    role_id,
                    f"schema validation failed; using built-in {role_id} contract: {error}",
                )
            )
            continue
        except ValueError as error:
            warnings.append(_warning(path, role_id, f"{error}; using built-in {role_id} contract."))
            continue

        if contract.id != role_id:
            warnings.append(
                _warning(
                    path,
                    role_id,
                    f"contract id {contract.id!r} does not match role directory {role_id!r}; "
                    f"using built-in {role_id} contract.",
                )
            )
            continue

        contracts[contract.id] = contract

    return RoleContractLoadResult(contracts=contracts, warnings=warnings)


def _validate_handoff_targets(
    contracts: dict[str, RoleContract],
    role_paths: dict[str, Path],
) -> list[RoleContractValidationIssue]:
    """Return validation issues for handoff targets that cannot be resolved."""
    valid_targets = {*contracts, "done"}
    errors: list[RoleContractValidationIssue] = []
    for role_id, contract in contracts.items():
        path = role_paths.get(role_id)
        if path is None:
            continue

        for rule in contract.handoff_rules:
            if rule.to_role_id in valid_targets:
                continue
            errors.append(
                _validation_issue(
                    path,
                    role_id,
                    f"unknown handoff target {rule.to_role_id!r}; add that role contract "
                    "or use an existing role id.",
                )
            )
    return errors


def validate_role_contracts(paths: CuratorPaths) -> RoleContractValidationResult:
    """Strictly validate editable role contracts without hiding errors as success."""
    contracts = default_role_contracts()
    errors: list[RoleContractValidationIssue] = []
    role_paths = {role.value: paths.role_contract_file(role) for role in RoleName}
    for role in RoleName:
        role_id = role.value
        path = role_paths[role_id]
        if not path.exists():
            continue

        default_contract = contracts[role_id]
        try:
            overlay = _load_contract_overlay(path)
            merged = _merge_contract_overlay(default_contract, overlay)
            contract = RoleContract.model_validate(merged)
        except YAMLError as error:
            errors.append(_validation_issue(path, role_id, f"invalid YAML: {error}"))
            continue
        except ValidationError as error:
            errors.append(_validation_issue(path, role_id, f"schema validation failed: {error}"))
            continue
        except ValueError as error:
            errors.append(_validation_issue(path, role_id, str(error)))
            continue

        if contract.id != role_id:
            errors.append(
                _validation_issue(
                    path,
                    role_id,
                    f"contract id {contract.id!r} does not match role directory {role_id!r}.",
                )
            )
            continue

        contracts[contract.id] = contract

    errors.extend(_validate_handoff_targets(contracts, role_paths))
    return RoleContractValidationResult(
        valid=not errors,
        contracts=contracts,
        errors=errors,
    )


def _write_new_file(path: Path, content: str) -> bool:
    """Write a file only when it does not already exist."""
    if path.exists():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def write_default_roles(paths: CuratorPaths) -> list[Path]:
    """Create missing default role files and return the files written."""
    written: list[Path] = []
    role_documents = default_role_documents()
    contract_documents = default_role_contract_documents()

    for role in RoleName:
        role_path = paths.role_file(role)
        if _write_new_file(role_path, role_documents[role]):
            written.append(role_path)

        contract_path = paths.role_contract_file(role)
        if _write_new_file(contract_path, contract_documents[role]):
            written.append(contract_path)

    return written

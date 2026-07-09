"""Provide fake provider fixtures used by scheduler and harness tests."""

from datetime import UTC, datetime

from curator.core.enums import EvidenceKind, LoopStepType, ProviderName, RoleName
from curator.core.schema import (
    EngineerImplementationOutput,
    EvidenceRef,
    HarnessRunSpec,
    PMConfirmationOutput,
    PMPlanOutput,
    QAValidationOutput,
)
from curator.providers.contracts import ProviderRunRequest, ProviderRunResponse


class CodingDeliveryFakeProvider:
    """Return deterministic role outputs for a full coding delivery loop."""

    provider_name = ProviderName.CODEX
    provider_profile_id = "codex-test"
    provider_session_id = "provider-session-codex-test"

    def run(self, spec: HarnessRunSpec):
        """Return the role output matching the requested loop step."""
        if spec.role is RoleName.PM and spec.step_type is LoopStepType.PLAN:
            return PMPlanOutput(
                summary="Plan is ready.",
                tasks=["Implement the requested change."],
                done_criteria=["Validation passes."],
            )
        if spec.role is RoleName.ENGINEER and spec.step_type is LoopStepType.IMPLEMENT:
            return EngineerImplementationOutput(
                summary="Implementation is complete.",
                changed_files=["src/app.py"],
                test_commands=["pytest"],
            )
        if spec.role is RoleName.QA and spec.step_type is LoopStepType.VALIDATE:
            return QAValidationOutput(
                passed=True,
                summary="Validation passed.",
                checks=["pytest"],
            )
        if spec.role is RoleName.QA and spec.step_type is LoopStepType.REVIEW:
            request = ProviderRunRequest.from_harness_spec(spec)
            evidence = EvidenceRef(
                id=f"evidence-review-{spec.iteration_id}",
                session_id=spec.session_id,
                loop_run_id=spec.loop_run_id,
                iteration_id=spec.iteration_id,
                kind=EvidenceKind.REVIEW,
                uri=f"provider-output://qa/review/{spec.id}",
                summary="Review passed.",
                producer_role=RoleName.QA,
                created_at=datetime(2026, 7, 8, tzinfo=UTC),
            )
            response = ProviderRunResponse.succeeded(
                request,
                ProviderName.CODEX,
                output={"summary": "Review passed."},
            )
            return response.model_copy(update={"evidence_refs": [evidence]})
        if spec.role is RoleName.PM and spec.step_type is LoopStepType.CONFIRM:
            return PMConfirmationOutput(
                confirmed=True,
                summary="PM confirms delivery.",
                aligned_done_criteria=["Validation passes."],
            )
        raise ValueError(
            "CodingDeliveryFakeProvider cannot run role and step pair: "
            f"{spec.role.value}/{spec.step_type.value}"
        )


def enable_live_mode(project_root) -> None:
    """Initialize state and bind a claude-code profile to both slots."""
    from curator.app import write_init_state
    from curator.core.enums import ProviderBindingStatus, ProviderProfileStatus
    from curator.core.paths import build_curator_paths
    from curator.core.schema import ProviderProfileRecord, RoleProviderBindingRecord
    from curator.state.db import connect_database, initialize_database
    from curator.state.repositories import (
        insert_provider_profile,
        insert_role_provider_binding,
    )

    write_init_state(project_root)
    now = datetime.now(UTC)
    connection = connect_database(build_curator_paths(project_root).database)
    try:
        initialize_database(connection)
        insert_provider_profile(
            connection,
            ProviderProfileRecord(
                id="claude-code",
                provider=ProviderName.CLAUDE_CODE,
                label="claude-code (local CLI)",
                credential_ref="local-cli",
                status=ProviderProfileStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                metadata={"binary": "claude", "version": "test"},
            ),
        )
        for role_instance_id in ("writer.default", "reviewer.default"):
            insert_role_provider_binding(
                connection,
                RoleProviderBindingRecord(
                    id=f"binding-{role_instance_id}-claude-code",
                    role_instance_id=role_instance_id,
                    provider_profile_id="claude-code",
                    status=ProviderBindingStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                ),
            )
    finally:
        connection.close()


def install_fake_claude(tmp_path, monkeypatch) -> None:
    """Put a scripted `claude` binary first on PATH for loop dispatch."""
    import os

    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        'print(json.dumps({"type": "result", "result": "done"}))\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

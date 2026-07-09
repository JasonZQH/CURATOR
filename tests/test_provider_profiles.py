"""Verify provider profile resolution helpers."""

from datetime import UTC, datetime

from curator.core.enums import (
    ProviderBindingStatus,
    ProviderName,
    ProviderProfileStatus,
    ProviderSessionStatus,
    QuotaStatus,
    RoleInstanceStatus,
    RoleName,
)
from curator.core.paths import build_curator_paths
from curator.core.schema import (
    ProviderProfileRecord,
    ProviderSessionRecord,
    RoleInstanceRecord,
    RoleProviderBindingRecord,
)
from curator.providers.profiles import (
    record_provider_quota_state,
    resolve_provider_identity,
    resolve_provider_profile_for_role,
)
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import (
    insert_provider_profile,
    insert_provider_session,
    insert_role_instance,
    insert_role_provider_binding,
    load_quota_state_for_profile,
)


def _connection(tmp_path):
    """Open an initialized database for provider profile tests."""
    connection = connect_database(build_curator_paths(tmp_path).database)
    initialize_database(connection)
    return connection


def test_provider_profile_resolution_uses_active_binding_session_and_quota(tmp_path):
    """Verify a role resolves to its active profile identity."""
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    connection = _connection(tmp_path)
    role = RoleInstanceRecord(
        id="engineer.1",
        role=RoleName.ENGINEER,
        label="Engineer 1",
        status=RoleInstanceStatus.IDLE,
        created_at=now,
        updated_at=now,
    )
    profile = ProviderProfileRecord(
        id="codex-work",
        provider=ProviderName.CODEX,
        label="Codex work",
        credential_ref="env:CODEX_WORK",
        status=ProviderProfileStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    binding = RoleProviderBindingRecord(
        id="binding-engineer-1-codex-work",
        role_instance_id=role.id,
        provider_profile_id=profile.id,
        status=ProviderBindingStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session = ProviderSessionRecord(
        id="provider-session-codex-work",
        provider_profile_id=profile.id,
        status=ProviderSessionStatus.ACTIVE,
        started_at=now,
    )

    insert_role_instance(connection, role)
    insert_provider_profile(connection, profile)
    insert_role_provider_binding(connection, binding)
    insert_provider_session(connection, session)
    quota = record_provider_quota_state(
        connection,
        provider_profile_id=profile.id,
        status=QuotaStatus.LIMITED,
        reason="manual observation",
        now=now,
    )

    resolved_profile = resolve_provider_profile_for_role(connection, role.id)
    identity = resolve_provider_identity(connection, role.id)

    assert resolved_profile == profile
    assert identity is not None
    assert identity.provider is ProviderName.CODEX
    assert identity.provider_profile_id == profile.id
    assert identity.provider_session_id == session.id
    assert identity.quota_status is QuotaStatus.LIMITED
    assert load_quota_state_for_profile(connection, profile.id) == quota


def test_provider_profile_resolution_ignores_inactive_or_paused_profiles(tmp_path):
    """Verify resolution skips unavailable bindings and profiles."""
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    connection = _connection(tmp_path)
    role = RoleInstanceRecord(
        id="engineer.1",
        role=RoleName.ENGINEER,
        label="Engineer 1",
        status=RoleInstanceStatus.IDLE,
        created_at=now,
        updated_at=now,
    )
    profile = ProviderProfileRecord(
        id="claude-team",
        provider=ProviderName.CLAUDE_CODE,
        label="Claude team",
        credential_ref="keychain:claude-team",
        status=ProviderProfileStatus.PAUSED,
        created_at=now,
        updated_at=now,
    )
    binding = RoleProviderBindingRecord(
        id="binding-engineer-1-claude-team",
        role_instance_id=role.id,
        provider_profile_id=profile.id,
        status=ProviderBindingStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )

    insert_role_instance(connection, role)
    insert_provider_profile(connection, profile)
    insert_role_provider_binding(connection, binding)

    assert resolve_provider_profile_for_role(connection, role.id) is None
    assert resolve_provider_identity(connection, role.id) is None

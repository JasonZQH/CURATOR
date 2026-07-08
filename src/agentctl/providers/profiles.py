"""Resolve role provider profiles and observed quota state."""

import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from agentctl.core.enums import (
    ProviderBindingStatus,
    ProviderName,
    ProviderProfileStatus,
    QuotaStatus,
)
from agentctl.core.models.base import CuratorModel
from agentctl.core.schema import ProviderProfileRecord, QuotaStateRecord
from agentctl.state.repositories import (
    insert_quota_state,
    load_active_provider_session,
    load_provider_binding_for_role,
    load_provider_profile,
    load_provider_profiles,
    load_quota_state_for_profile,
    load_role_provider_bindings,
)


class ProviderIdentity(CuratorModel):
    """Describe the resolved provider identity for one role instance."""

    provider: ProviderName
    provider_profile_id: str
    provider_session_id: str | None = None
    quota_status: QuotaStatus = QuotaStatus.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeMode(CuratorModel):
    """Describe whether runs can use a configured real provider."""

    label: str
    detail: str


def resolve_runtime_mode(connection: sqlite3.Connection) -> RuntimeMode:
    """Return the effective execution mode from profiles and bindings."""
    real_profiles = [
        profile
        for profile in load_provider_profiles(connection)
        if profile.status is ProviderProfileStatus.ACTIVE
    ]
    if not real_profiles:
        return RuntimeMode(label="setup", detail="no provider profiles configured")

    real_profile_ids = {profile.id for profile in real_profiles}
    bound = any(
        binding.status is ProviderBindingStatus.ACTIVE
        and binding.provider_profile_id in real_profile_ids
        for binding in load_role_provider_bindings(connection)
    )
    if not bound:
        return RuntimeMode(
            label="setup",
            detail="profiles exist but no agent is bound (/agent bind <agent> <profile>)",
        )

    return RuntimeMode(label="live", detail="real provider bound")


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def resolve_provider_profile_for_role(
    connection: sqlite3.Connection, role_instance_id: str
) -> ProviderProfileRecord | None:
    """Return the active provider profile bound to a role instance."""
    binding = load_provider_binding_for_role(connection, role_instance_id)
    if binding is None:
        return None

    profile = load_provider_profile(connection, binding.provider_profile_id)
    if profile is None or profile.status is not ProviderProfileStatus.ACTIVE:
        return None

    return profile


def resolve_provider_identity(
    connection: sqlite3.Connection, role_instance_id: str
) -> ProviderIdentity | None:
    """Return the provider identity, session, and quota for a role instance."""
    profile = resolve_provider_profile_for_role(connection, role_instance_id)
    if profile is None:
        return None

    session = load_active_provider_session(connection, profile.id)
    quota = load_quota_state_for_profile(connection, profile.id)
    return ProviderIdentity(
        provider=profile.provider,
        provider_profile_id=profile.id,
        provider_session_id=session.id if session else None,
        quota_status=quota.status if quota else QuotaStatus.UNKNOWN,
        metadata={"credential_ref": profile.credential_ref},
    )


def record_provider_quota_state(
    connection: sqlite3.Connection,
    provider_profile_id: str,
    status: QuotaStatus,
    reason: str,
    now: datetime | None = None,
) -> QuotaStateRecord:
    """Persist one observed provider quota state and return it."""
    observed_at = now or _now()
    quota = QuotaStateRecord(
        id=f"quota-{provider_profile_id}-{observed_at.strftime('%Y%m%d%H%M%S')}",
        provider_profile_id=provider_profile_id,
        status=status,
        reason=reason,
        observed_at=observed_at,
    )
    insert_quota_state(connection, quota)
    return quota

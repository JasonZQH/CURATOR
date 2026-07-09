"""Resolve provider drivers from profiles and slot bindings."""

import sqlite3
from pathlib import Path

from curator.core.enums import ProviderName, ProviderProfileStatus, QuotaStatus
from curator.core.schema import CompiledLoopStep, ProviderProfileRecord
from curator.providers.claude_code import ClaudeCodeDriver
from curator.providers.codex_cli import CodexCliDriver
from curator.providers.driver import ProviderDriver
from curator.state.repositories import (
    load_active_provider_session,
    load_provider_binding_for_role,
    load_provider_profile,
    load_provider_profiles,
    load_quota_state_for_profile,
)

# Canonical role instances that carry functional-slot provider bindings.
SLOT_ROLE_INSTANCES: dict[str, str] = {
    "writer": "writer.default",
    "reviewer": "reviewer.default",
}


class ProviderConfigurationError(RuntimeError):
    """Signal that a provider-backed step has no real provider driver."""


def driver_for_profile(
    profile: ProviderProfileRecord,
    project_root: Path | str,
    slot: str | None = None,
) -> ProviderDriver:
    """Return an async driver for one provider profile."""
    session = None
    quota_status = QuotaStatus.UNKNOWN.value
    if profile.provider is ProviderName.CLAUDE_CODE:
        return ClaudeCodeDriver(
            project_root,
            slot=slot,
            provider_profile_id=profile.id,
            provider_session_id=session.id if session else None,
            quota_status=quota_status,
        )
    if profile.provider is ProviderName.CODEX:
        return CodexCliDriver(
            project_root,
            slot=slot,
            provider_profile_id=profile.id,
            provider_session_id=session.id if session else None,
            quota_status=quota_status,
        )
    raise ProviderConfigurationError(f"Unsupported provider profile: {profile.provider.value}")


def _driver_for_bound_profile(
    connection: sqlite3.Connection,
    profile: ProviderProfileRecord,
    project_root: Path | str,
    slot: str | None,
) -> ProviderDriver:
    """Return a driver with ledger identity loaded from runtime provider state."""
    driver = driver_for_profile(profile, project_root, slot=slot)
    session = load_active_provider_session(connection, profile.id)
    quota = load_quota_state_for_profile(connection, profile.id)
    if hasattr(driver, "provider_session_id"):
        driver.provider_session_id = session.id if session else None
    if hasattr(driver, "quota_status"):
        driver.quota_status = (quota.status if quota else QuotaStatus.UNKNOWN).value
    return driver


def _profile_for_slot(
    connection: sqlite3.Connection, slot: str | None
) -> ProviderProfileRecord | None:
    """Return the active provider profile bound to a functional slot."""
    role_instance_id = SLOT_ROLE_INSTANCES.get(slot or "")
    if role_instance_id is None:
        return None
    binding = load_provider_binding_for_role(connection, role_instance_id)
    if binding is None:
        return None
    return load_provider_profile(connection, binding.provider_profile_id)


def _fallback_profile(connection: sqlite3.Connection) -> ProviderProfileRecord | None:
    """Return the single active real profile when exactly one is configured."""
    profiles = [
        profile
        for profile in load_provider_profiles(connection)
        if profile.status is ProviderProfileStatus.ACTIVE
    ]
    return profiles[0] if len(profiles) == 1 else None


def resolve_provider_for_step(
    connection: sqlite3.Connection,
    step: CompiledLoopStep,
    project_root: Path | str,
) -> ProviderDriver:
    """Resolve the real provider driver for one step from slot binding or profile."""
    profile = _profile_for_slot(connection, step.slot) or _fallback_profile(connection)
    if profile is None:
        slot_hint = f" for slot {step.slot}" if step.slot else ""
        raise ProviderConfigurationError(
            "No active provider profile is bound"
            f"{slot_hint}. Run `curator provider add <name>` and bind writer/reviewer."
        )
    return _driver_for_bound_profile(connection, profile, project_root, slot=step.slot)

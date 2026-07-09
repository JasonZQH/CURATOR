"""Create provider profiles from locally installed CLIs."""

import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from curator.core.enums import ProviderName, ProviderProfileStatus
from curator.core.schema import ProviderProfileRecord
from curator.providers.detect import provider_binary
from curator.state.repositories import insert_provider_profile, load_provider_profiles

_PROVIDER_ALIASES: dict[str, ProviderName] = {
    "claude-code": ProviderName.CLAUDE_CODE,
    "claude": ProviderName.CLAUDE_CODE,
    "codex": ProviderName.CODEX,
}


@dataclass(frozen=True)
class ProviderAddResult:
    """Describe the outcome of a provider add attempt."""

    created: bool
    profile: ProviderProfileRecord | None
    message: str


@dataclass(frozen=True)
class ProviderCliAvailability:
    """Describe whether a provider CLI can be executed locally."""

    available: bool
    version: str
    error: str = ""


def resolve_provider_name(alias: str) -> ProviderName | None:
    """Return the provider enum for a user-supplied alias."""
    return _PROVIDER_ALIASES.get(alias.strip().lower())


def _detect_version(provider: ProviderName) -> ProviderCliAvailability:
    """Return the provider CLI availability and version details."""
    binary = provider_binary(provider)
    if binary is None:
        return ProviderCliAvailability(available=False, version="", error="no CLI binary")
    if shutil.which(binary) is None:
        return ProviderCliAvailability(available=False, version="", error="not found on PATH")
    try:
        completed = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return ProviderCliAvailability(available=False, version="", error=str(error))
    version = (completed.stdout or completed.stderr or "").strip().splitlines()
    if completed.returncode != 0:
        detail = version[0] if version else f"exit {completed.returncode}"
        return ProviderCliAvailability(available=False, version="", error=detail)
    return ProviderCliAvailability(available=True, version=version[0] if version else "unknown")


def add_provider_profile(
    connection: sqlite3.Connection,
    alias: str,
    now: datetime | None = None,
) -> ProviderAddResult:
    """Detect a provider CLI and persist a provider profile for it."""
    provider = resolve_provider_name(alias)
    if provider is None:
        return ProviderAddResult(
            created=False,
            profile=None,
            message=f"Unknown provider: {alias}. Use claude-code or codex.",
        )

    availability = _detect_version(provider)
    if not availability.available:
        binary = provider_binary(provider)
        return ProviderAddResult(
            created=False,
            profile=None,
            message=f"{provider.value} CLI ({binary}) is unavailable: {availability.error}.",
        )

    profile_id = provider.value
    if any(profile.id == profile_id for profile in load_provider_profiles(connection)):
        return ProviderAddResult(
            created=False,
            profile=None,
            message=f"Provider profile already exists: {profile_id}",
        )

    timestamp = now or datetime.now(UTC)
    profile = ProviderProfileRecord(
        id=profile_id,
        provider=provider,
        label=f"{provider.value} (local CLI)",
        credential_ref="local-cli",
        status=ProviderProfileStatus.ACTIVE,
        created_at=timestamp,
        updated_at=timestamp,
        metadata={
            "binary": provider_binary(provider) or "unknown",
            "version": availability.version,
        },
    )
    insert_provider_profile(connection, profile)
    return ProviderAddResult(
        created=True,
        profile=profile,
        message=f"Added provider profile {profile_id} ({availability.version}).",
    )

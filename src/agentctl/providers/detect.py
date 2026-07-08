"""Detect locally executable provider CLIs for setup guidance."""

import subprocess
from pathlib import Path

from agentctl.core.enums import ProviderName

_PROVIDER_BINARIES: dict[ProviderName, str] = {
    ProviderName.CLAUDE_CODE: "claude",
    ProviderName.CODEX: "codex",
}


def provider_binary(provider: ProviderName) -> str | None:
    """Return the CLI binary name for one detectable provider."""
    return _PROVIDER_BINARIES.get(provider)


def detect_available_providers(project_root: Path | str | None = None) -> list[ProviderName]:
    """Return providers whose CLI binaries execute a version command."""
    _ = project_root
    providers = []
    for provider, binary in _PROVIDER_BINARIES.items():
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            providers.append(provider)
    return providers


def provider_setup_hint() -> str:
    """Return the single guidance string for connecting a real provider."""
    return "curator provider add claude-code — connect Claude Code or Codex"

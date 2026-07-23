"""Guard the repository against synthetic providers and committed seed/mock state.

Curator's contract is "no synthetic provider, no fallback theater": the shipping code
never fabricates a provider run, and a fresh project starts empty. These guards fail the
build if that ever regresses — a mock/fake provider is added to shipping code, local
`.curator/` state or a SQLite ledger is committed, or `curator init` seeds runtime rows.
"""

import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from curator.app import write_init_state
from curator.core.enums import ProviderName
from curator.core.paths import build_curator_paths

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "curator"

# Real provider backends Curator is allowed to ship. A synthetic/mock provider must never
# be added here — it would let a run report success without a real CLI executing.
_ALLOWED_PROVIDERS = {"codex", "claude-code"}

# A re-introduced fake provider would most likely appear as a class like MockProvider or
# FakeDriver in shipping code. Matched narrowly so ordinary words never trip the guard.
_SYNTHETIC_PROVIDER = re.compile(
    r"class\s+\w*(Mock|Fake|Stub|Synthetic|Dummy)\w*(Provider|Driver)\b"
)


def test_provider_names_are_real_backends_only():
    """Verify ProviderName stays limited to real provider backends, never a synthetic one."""
    assert {provider.value for provider in ProviderName} == _ALLOWED_PROVIDERS, (
        "ProviderName must contain only real provider backends. Adding a synthetic/mock "
        "provider breaks Curator's 'no fallback theater' guarantee."
    )


def test_shipping_code_defines_no_synthetic_provider():
    """Verify src/ contains no mock/fake/stub provider or driver class."""
    offenders = []
    for module in _SRC.rglob("*.py"):
        for lineno, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
            if _SYNTHETIC_PROVIDER.search(line):
                offenders.append(f"{module.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "Shipping code must not define a synthetic provider:\n" + "\n".join(
        offenders
    )


def test_no_curator_state_or_sqlite_is_tracked():
    """Verify no local Curator state directory or SQLite ledger is committed to the repo."""
    try:
        tracked = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is unavailable; state-tracking guard runs in a git checkout only")

    bad = [
        path
        for path in tracked
        if path.startswith(".curator/")
        or "/.curator/" in path
        or path.endswith((".sqlite", ".sqlite3"))
    ]
    assert not bad, (
        "Local Curator state and SQLite ledgers must never be committed "
        "(they are seed/mock runtime data):\n" + "\n".join(bad)
    )


def test_fresh_init_seeds_no_runtime_rows(tmp_path):
    """Verify a fresh curator init produces an empty ledger — no seeded sessions or runs."""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "README.md").write_text("# fixture\n")

    write_init_state(tmp_path)

    database = build_curator_paths(tmp_path).database
    connection = sqlite3.connect(database)
    try:
        for table in ("sessions", "goals", "provider_runs", "loop_runs", "loop_iterations"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, (
                f"fresh curator init seeded {count} row(s) into {table}; "
                "a new project must start with an empty ledger"
            )
    finally:
        connection.close()

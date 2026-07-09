"""Run the guided setup wizard: roles, providers, login, one consent write."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from curator.core.enums import ProviderBindingStatus
from curator.core.paths import build_curator_paths
from curator.core.schema import RoleProviderBindingRecord
from curator.diagnostics.preflight import PreflightCheck, probe_provider
from curator.providers.setup import add_provider_profile
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import insert_role_provider_binding

AskFn = Callable[[str], str]
SayFn = Callable[[str], None]

_SEATS: tuple[tuple[str, str], ...] = (
    ("writer", "writer.default"),
    ("reviewer", "reviewer.default"),
)
_PROVIDER_KEYS = ("claude-code", "codex")

_CANCELLED = "Setup cancelled — nothing was written."


@dataclass(frozen=True)
class WizardOutcome:
    """Describe whether the wizard applied changes and what to tell the user."""

    applied: bool
    message: str


def run_setup_wizard(
    project_root: Path | str, ask: AskFn = input, say: SayFn = print
) -> WizardOutcome:
    """Run the three-step setup wizard; nothing is written before consent."""
    try:
        return _run(Path(project_root), ask, say)
    except EOFError:
        return WizardOutcome(applied=False, message=_CANCELLED)


def _run(project_root: Path, ask: AskFn, say: SayFn) -> WizardOutcome:
    """Drive the wizard steps against injectable line IO."""
    say(
        "\n".join(
            [
                "Setup · Step 1/3 — Team roles",
                "",
                "Curator delivers each goal with one loop:",
                "  implement → verify → review → confirm",
                "Two seats are executed by real providers:",
                "  writer    implements code (engineer role)",
                "  reviewer  reviews with fresh context (qa role, read-only)",
                "Custom roles are planned for a later version.",
                "",
                "  1) Use the default team (recommended)",
                "  2) Cancel setup",
            ]
        )
    )
    if _choice(ask, {"", "1"}, {"2"}) is None:
        return WizardOutcome(applied=False, message=_CANCELLED)

    detected = [probe_provider(key) for key in _PROVIDER_KEYS]
    usable = [
        (key, check)
        for key, check in zip(_PROVIDER_KEYS, detected)
        if check.status != "fail"
    ]
    if not usable:
        lines = ["No provider CLIs found. Install one and rerun /setup:"]
        lines.extend(f"  ✗ {check.detail}" for check in detected)
        lines.extend(
            f"  fix: {check.fix}" for check in detected if check.fix is not None
        )
        return WizardOutcome(applied=False, message="\n".join(lines))

    say(
        "\n".join(
            [
                "",
                "Setup · Step 2/3 — Providers",
                "Detected CLIs:",
                *(
                    f"  {index}) {check.detail}"
                    for index, (_, check) in enumerate(usable, start=1)
                ),
            ]
        )
    )
    seat_choices: dict[str, tuple[str, PreflightCheck]] = {}
    for seat_label, _ in _SEATS:
        picked = _pick_provider(ask, say, seat_label, usable, seat_choices)
        if picked is None:
            return WizardOutcome(applied=False, message=_CANCELLED)
        seat_choices[seat_label] = picked

    summary = [
        "",
        "Setup · Step 3/3 — Confirm",
        "Will create: .curator/ (team contracts · memory · SQLite ledger)",
    ]
    for seat_label, role_instance_id in _SEATS:
        key, check = seat_choices[seat_label]
        summary.append(f"  {role_instance_id} ← {key} ({check.detail})")
        if check.status == "warn":
            summary.append(f"      note: {check.fix}")
    summary.extend(["  1) Apply and finish", "  2) Cancel (nothing written)"])
    say("\n".join(summary))
    if _choice(ask, {"", "1"}, {"2"}) is None:
        return WizardOutcome(applied=False, message=_CANCELLED)

    return _apply(project_root, seat_choices)


def _choice(ask: AskFn, accept: set[str], reject: set[str]) -> str | None:
    """Read one menu answer; return None on rejection, the answer otherwise."""
    while True:
        answer = ask("> ").strip().lower()
        if answer in reject:
            return None
        if answer in accept:
            return answer


def _pick_provider(
    ask: AskFn,
    say: SayFn,
    seat_label: str,
    usable: list[tuple[str, PreflightCheck]],
    prior: dict[str, tuple[str, PreflightCheck]],
) -> tuple[str, PreflightCheck] | None:
    """Ask which detected provider should power one seat."""
    same_hint = ", Enter = same as writer" if prior else ""
    say(f"{seat_label} → choose provider [1-{len(usable)}{same_hint}, q = cancel]:")
    while True:
        answer = ask("> ").strip().lower()
        if answer == "q":
            return None
        if not answer and prior:
            return prior["writer"]
        if answer.isdigit() and 1 <= int(answer) <= len(usable):
            picked = usable[int(answer) - 1]
            if picked[1].status == "warn":
                say(f"  note: {picked[1].detail} — {picked[1].fix}")
            return picked


def _apply(
    project_root: Path, seat_choices: dict[str, tuple[str, PreflightCheck]]
) -> WizardOutcome:
    """Write init state, provider profiles, and seat bindings in one pass."""
    from curator.app import write_init_state

    write_init_state(project_root)
    now = datetime.now(UTC)
    lines = ["Setup complete."]
    connection = connect_database(build_curator_paths(project_root).database)
    try:
        initialize_database(connection)
        for key in {key for key, _ in seat_choices.values()}:
            result = add_provider_profile(connection, key)
            lines.append(result.message)
        for seat_label, role_instance_id in _SEATS:
            key, _ = seat_choices[seat_label]
            insert_role_provider_binding(
                connection,
                RoleProviderBindingRecord(
                    id=f"binding-{role_instance_id}-{key}",
                    role_instance_id=role_instance_id,
                    provider_profile_id=key,
                    status=ProviderBindingStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                ),
            )
            lines.append(f"Bound {role_instance_id} → {key}")
    finally:
        connection.close()
    lines.append("Mode: live — type what you want to work on.")
    return WizardOutcome(applied=True, message="\n".join(lines))

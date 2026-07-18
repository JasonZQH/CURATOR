"""Provide a small event-driven setup state machine for line and TUI drivers."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from curator.diagnostics.preflight import PreflightCheck
from curator.providers.setup import add_provider_profile
from curator.core.enums import ProviderBindingStatus, RoleName
from curator.core.paths import build_curator_paths
from curator.core.schema import RoleProviderBindingRecord
from curator.runtime.role_pool import ensure_default_role_pool
from curator.state.db import connect_database, initialize_database
from curator.state.repositories import insert_role_provider_binding


@dataclass(frozen=True)
class Say:
    """Tell a driver to render explanatory text."""

    text: str


@dataclass(frozen=True)
class Ask:
    """Tell a driver to present a set of answer options."""

    prompt: str
    options: tuple[str, ...]


@dataclass(frozen=True)
class Probe:
    """Tell a driver to run a provider environment probe."""

    providers: tuple[str, ...]


@dataclass(frozen=True)
class Done:
    """Tell a driver that setup has reached its terminal outcome."""

    outcome: "WizardResult"


@dataclass(frozen=True)
class WizardResult:
    """Describe setup success or cancellation without rendering concerns."""

    applied: bool
    message: str


_SEATS: tuple[tuple[str, str, str, RoleName], ...] = (
    ("pm", "maindeck.default", "PM (main deck)", RoleName.PM),
    ("engineer", "writer.default", "Engineer", RoleName.ENGINEER),
    ("reviewer", "reviewer.default", "Reviewer", RoleName.QA),
)
_CANCELLED = "Setup cancelled — nothing was written."


class SetupFlow:
    """Advance setup through roles, provider seats, and one final consent."""

    def __init__(self, project_root: Path | str, compact_line: bool = False) -> None:
        """Create a fresh flow that has not touched project-local state."""
        self.project_root = Path(project_root)
        self.compact_line = compact_line
        self.seat_index = 0
        self.checks: tuple[tuple[str, PreflightCheck], ...] = ()
        self.choices: dict[str, tuple[str, PreflightCheck]] = {}
        self.stage = "roles"

    def start(self) -> tuple[Say | Ask | Probe | Done, ...]:
        """Return the opening explanation and the default-team choice."""
        return (
            Say(
                "Setup · Step 1/3 — Team seats\n\n"
                "PM (main deck) plans read-only, Engineer implements, Reviewer verifies read-only.\n"
                "Custom roles are not selectable in v0.1.0; edit role contracts after setup if needed."
            ),
            Ask(
                "Use the default team?",
                ("Use PM, Engineer, and Reviewer (recommended)", "Cancel setup"),
            ),
        )

    def advance(self, answer: str) -> tuple[Say | Ask | Probe | Done, ...]:
        """Consume one textual answer and emit the next state-machine events."""
        value = answer.strip().lower()
        if self.stage == "roles":
            if value in {"2", "q", "cancel", "no"}:
                return (Done(WizardResult(False, _CANCELLED)),)
            if value not in {"", "1", "yes", "y"}:
                return self.start()[1:]
            self.stage = "providers"
            return (Probe(("claude-code", "codex")),)
        if self.stage == "providers":
            return self._choose_provider(value)
        if self.stage == "confirm":
            if value in {"", "1", "yes", "y"}:
                return (Done(self.apply()),)
            return (Done(WizardResult(False, _CANCELLED)),)
        return (Done(WizardResult(False, _CANCELLED)),)

    def set_probes(self, checks: list[tuple[str, PreflightCheck]]) -> tuple[Say | Ask | Probe | Done, ...]:
        """Supply provider probe results and open the first seat selector."""
        usable = tuple(item for item in checks if item[1].status != "fail")
        if not usable:
            detail = "\n".join(f"  ✗ {check.detail}" for _, check in checks)
            return (Done(WizardResult(False, f"No provider CLIs found. Install one and rerun /setup:\n{detail}")),)
        self.checks = usable
        detected = "\n".join(f"  {key}: {check.detail}" for key, check in usable)
        return (Say(f"Setup · Step 2/3 — Providers\nDetected CLIs:\n{detected}"), *self._seat_prompt())

    def _choose_provider(self, value: str) -> tuple[Say | Ask | Probe | Done, ...]:
        """Apply one seat answer and advance to the next seat or confirmation."""
        if value in {"q", "cancel"}:
            return (Done(WizardResult(False, _CANCELLED)),)
        seat_key = _SEATS[self.seat_index][0]
        if self.compact_line and self.seat_index == 1:
            picked = self.choices["pm"] if not value else self._provider_for_value(value)
            if picked is None:
                return self._seat_prompt()
            self.choices["engineer"] = self.choices["pm"]
            self.choices["reviewer"] = picked
            self.seat_index = len(_SEATS)
            self.stage = "confirm"
            return (Say(self._confirmation_text()), Ask("Apply and finish?", ("Apply and finish", "Cancel")))
        if not value and self.choices:
            picked = self.choices["pm"]
        elif value.isdigit() and 1 <= int(value) <= len(self.checks):
            picked = self.checks[int(value) - 1]
        else:
            return self._seat_prompt()
        self.choices[seat_key] = picked
        self.seat_index += 1
        if self.seat_index < len(_SEATS):
            return self._seat_prompt()
        self.stage = "confirm"
        return (Say(self._confirmation_text()), Ask("Apply and finish?", ("Apply and finish", "Cancel")))

    def _provider_for_value(self, value: str) -> tuple[str, PreflightCheck] | None:
        """Resolve one numbered provider answer or return None for invalid input."""
        if value.isdigit() and 1 <= int(value) <= len(self.checks):
            return self.checks[int(value) - 1]
        return None

    def _confirmation_text(self) -> str:
        """Render the final consent summary for all three named seats."""
        lines = ["Setup · Step 3/3 — Confirm", "", "Bindings to create:"]
        lines.extend(f"  {label} ← {self.choices[key][0]}" for key, _, label, _ in _SEATS)
        return "\n".join(lines)

    def _seat_prompt(self) -> tuple[Say | Ask | Probe | Done, ...]:
        """Return the next seat's labelled provider options."""
        key, _, label, _ = _SEATS[self.seat_index]
        same = (", Enter = same as PM" if self.choices else "")
        return (Say(f"Setup · {label}"), Ask(f"Choose provider [1-{len(self.checks)}{same}]", tuple(check.detail for _, check in self.checks)))

    def apply(self) -> WizardResult:
        """Write the approved three-seat provider configuration."""
        from curator.app import write_init_state

        write_init_state(self.project_root)
        now = datetime.now(UTC)
        connection = connect_database(build_curator_paths(self.project_root).database)
        lines = ["Setup complete."]
        try:
            initialize_database(connection)
            ensure_default_role_pool(connection, now=now)
            for provider, _ in self.choices.values():
                result = add_provider_profile(connection, provider)
                if result.message not in lines:
                    lines.append(result.message)
            for seat_key, role_instance_id, label, _ in _SEATS:
                provider, _ = self.choices[seat_key]
                insert_role_provider_binding(
                    connection,
                    RoleProviderBindingRecord(
                        id=f"binding-{role_instance_id}-{provider}",
                        role_instance_id=role_instance_id,
                        provider_profile_id=provider,
                        status=ProviderBindingStatus.ACTIVE,
                        created_at=now,
                        updated_at=now,
                    ),
                )
                lines.append(f"Bound {label} ({role_instance_id}) → {provider}")
        finally:
            connection.close()
        lines.append("Mode: live — type what you want to work on.")
        return WizardResult(True, "\n".join(lines))

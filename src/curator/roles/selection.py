"""Select candidate roles from machine-readable role contracts."""

from collections.abc import Iterable

from curator.core.schema import RoleContract, RoleSelection


def _normalize_signal(signal: str) -> str:
    """Normalize one role-selection signal for exact deterministic matching."""
    return signal.strip().lower().replace("_", "-")


def _role_signals(contract: RoleContract) -> set[str]:
    """Return all normalized signals declared by one role contract."""
    return {
        _normalize_signal(signal)
        for signal in [*contract.when_to_involve, *contract.capability_tags]
    }


def _selection_reason(role_id: str, matched_signals: list[str]) -> str:
    """Return the auditable reason for selecting a role candidate."""
    return f"Selected {role_id} because it matched: {', '.join(matched_signals)}."


def select_role_candidates(
    contracts: dict[str, RoleContract],
    task_signals: Iterable[str],
    excluded_role_ids: set[str] | None = None,
) -> list[RoleSelection]:
    """Select role candidates by matching task signals against role contracts."""
    excluded = excluded_role_ids or set()
    normalized_task_signals = [_normalize_signal(signal) for signal in task_signals]
    selections: list[RoleSelection] = []

    for role_id, contract in contracts.items():
        if role_id in excluded:
            continue

        matched_signals = [
            signal
            for signal in normalized_task_signals
            if signal in _role_signals(contract)
        ]
        if not matched_signals:
            continue

        selections.append(
            RoleSelection(
                role_id=contract.id,
                display_name=contract.display_name,
                matched_signals=matched_signals,
                score=len(matched_signals),
                reason=_selection_reason(contract.id, matched_signals),
            )
        )

    return sorted(selections, key=lambda selection: (-selection.score, selection.role_id))

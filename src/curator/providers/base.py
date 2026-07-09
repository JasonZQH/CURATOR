"""Define the provider protocol used by the scheduler and harness."""

from typing import Protocol, TypeAlias

from curator.core.schema import (
    EngineerImplementationOutput,
    HarnessRunSpec,
    PMConfirmationOutput,
    PMPlanOutput,
    QAValidationOutput,
)

RoleOutput: TypeAlias = (
    PMPlanOutput | EngineerImplementationOutput | QAValidationOutput | PMConfirmationOutput
)


class Provider(Protocol):
    """Define the provider boundary consumed by the harness runtime."""

    def run(self, spec: HarnessRunSpec) -> RoleOutput:
        """Execute one harness run spec and return one role output schema."""
        ...

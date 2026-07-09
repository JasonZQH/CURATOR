"""Define streaming provider event contracts for the async driver layer."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable

from pydantic import Field

from curator.core.models.base import CuratorModel


class ProviderEventKind(str, Enum):
    """Constrain the event kinds emitted by a running provider."""

    STARTED = "started"
    OUTPUT_CHUNK = "output_chunk"
    TOOL_CALL = "tool_call"
    PERMISSION_REQUEST = "permission_request"
    USAGE = "usage"
    COMPLETED = "completed"
    FAILED = "failed"


class ProviderEvent(CuratorModel):
    """Describe one observable event from a running provider."""

    kind: ProviderEventKind
    provider_run_id: str
    sequence: int = 0
    label: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


ProviderEventCallback = Callable[[ProviderEvent], None]

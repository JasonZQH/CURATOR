"""Define Curator session, task, message, and event models."""

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from curator.core.enums import EventType, MessageType, RoleName, SessionMode, TaskStatus
from curator.core.models.base import CuratorModel


class SessionRecord(CuratorModel):
    """Describe a durable Curator work session."""

    id: str
    project_root: Path
    mode: SessionMode
    created_at: datetime
    updated_at: datetime
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(CuratorModel):
    """Describe one scheduler-visible unit of role work."""

    id: str
    session_id: str
    role: RoleName
    status: TaskStatus
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageRecord(CuratorModel):
    """Describe one routed role message in a session."""

    id: str
    session_id: str
    role: RoleName
    type: MessageType
    content: str
    created_at: datetime
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventRecord(CuratorModel):
    """Describe one durable state transition event."""

    id: str
    session_id: str
    type: EventType
    created_at: datetime
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

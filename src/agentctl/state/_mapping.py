"""Share SQLite serialization and record mapping helpers."""

import json
import sqlite3
from datetime import datetime
from typing import Any, Callable, TypeVar

RecordT = TypeVar("RecordT")
MapperT = Callable[[sqlite3.Row], dict[str, Any]]


def json_dumps(value: dict[str, Any]) -> str:
    """Serialize a metadata or payload dictionary for SQLite storage."""
    return json.dumps(value, sort_keys=True)


def json_loads(value: str) -> dict[str, Any]:
    """Deserialize a SQLite JSON text column into a dictionary."""
    return json.loads(value)


def iso_or_none(value: datetime | None) -> str | None:
    """Serialize an optional datetime to ISO text for SQLite storage."""
    if value is None:
        return None

    return value.isoformat()


def fetch_one(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
    factory: type[RecordT],
    mapper: MapperT,
) -> RecordT | None:
    """Load one row and convert it into the requested record type."""
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        return None

    return factory(**mapper(row))


def fetch_many(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
    factory: type[RecordT],
    mapper: MapperT,
) -> list[RecordT]:
    """Load matching rows and convert them into the requested record type."""
    rows = connection.execute(query, parameters).fetchall()
    return [factory(**mapper(row)) for row in rows]

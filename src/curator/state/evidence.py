"""Persist and load Curator evidence reference records."""

import sqlite3
from typing import Any

from curator.core.schema import EvidenceRef
from curator.state._mapping import fetch_many, json_dumps, json_loads, maybe_commit


def insert_evidence_ref(connection: sqlite3.Connection, evidence: EvidenceRef) -> None:
    """Insert or replace one evidence reference record."""
    connection.execute(
        """
        insert or replace into evidence_refs (
            id, session_id, loop_run_id, iteration_id, kind, uri, summary, producer_role,
            created_at, content_hash, metadata_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence.id,
            evidence.session_id,
            evidence.loop_run_id,
            evidence.iteration_id,
            evidence.kind.value,
            evidence.uri,
            evidence.summary,
            evidence.producer_role.value,
            evidence.created_at.isoformat(),
            evidence.content_hash,
            json_dumps(evidence.metadata),
        ),
    )
    maybe_commit(connection)


def _map_evidence_ref(row: sqlite3.Row) -> dict[str, Any]:
    """Map an evidence_refs row into EvidenceRef keyword arguments."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "loop_run_id": row["loop_run_id"],
        "iteration_id": row["iteration_id"],
        "kind": row["kind"],
        "uri": row["uri"],
        "summary": row["summary"],
        "producer_role": row["producer_role"],
        "created_at": row["created_at"],
        "content_hash": row["content_hash"],
        "metadata": json_loads(row["metadata_json"]),
    }


def load_evidence_refs(connection: sqlite3.Connection, loop_run_id: str) -> list[EvidenceRef]:
    """Load evidence references for a loop run in creation order."""
    return fetch_many(
        connection,
        "select * from evidence_refs where loop_run_id = ? order by created_at, id",
        (loop_run_id,),
        EvidenceRef,
        _map_evidence_ref,
    )


def load_evidence_refs_for_run(
    connection: sqlite3.Connection, loop_run_id: str
) -> list[EvidenceRef]:
    """Load evidence references for a loop run in creation order."""
    return load_evidence_refs(connection, loop_run_id)

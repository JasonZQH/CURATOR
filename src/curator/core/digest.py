"""Compute the one content-hash form Curator records on evidence.

Every evidence producer writes `content_hash`, and a content-addressed artifact store will
key on exactly these strings — so the form is defined once here rather than spelled out at
each producer, where the four of them could drift apart a character at a time.
"""

import hashlib
import json
from typing import Any

_PREFIX = "sha256"


def digest_bytes(data: bytes) -> str:
    """Return the content hash of bytes Curator has persisted."""
    return f"{_PREFIX}:{hashlib.sha256(data).hexdigest()}"


def digest_payload(payload: Any) -> str:
    """Return the content hash of a JSON-serializable payload.

    Canonical form is sorted-key, separator-tight JSON, so the digest depends on the data
    and not on the order fields happen to be declared in: reordering a model field must
    never silently change the hash of evidence already on the ledger. It is also plain
    enough to reproduce outside Curator, which is the point of publishing a hash at all.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_bytes(canonical.encode("utf-8"))

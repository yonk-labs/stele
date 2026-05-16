"""Translation between Stele's chunk_id and chunkshop's row schema.

Pure string/number translation. **No chunkshop import** — chunkshop is
vector-only and returns bare ``(doc_id, seq_num, distance)`` tuples; this
module turns those into Stele's ``{artifact_id}:{ordinal}`` chunk_id and a
normalized score, so no chunkshop-native object ever reaches a SearchHit.
"""

from __future__ import annotations

from stele.core.exceptions import BackendError


def stele_chunk_id(artifact_id: str, ordinal: int) -> str:
    """Stele's stable chunk id. Matches ``ChunkRecord.chunk_id``."""
    return f"{artifact_id}:{ordinal}"


def split_chunk_id(chunk_id: str) -> tuple[str, int]:
    """Inverse of :func:`stele_chunk_id`.

    The ordinal is always the final ``:``-delimited segment, so an
    artifact_id that itself contains ``:`` still round-trips. Anything that
    is not ``<non-empty>:<non-negative-int>`` raises ``BackendError``.
    """
    artifact_id, sep, ordinal_str = chunk_id.rpartition(":")
    if not sep or not artifact_id or not ordinal_str:
        raise BackendError(f"malformed chunk_id: {chunk_id!r}")
    if not ordinal_str.isdigit():  # rejects '', '-1', '1.5', 'notanint'
        raise BackendError(f"malformed chunk_id ordinal: {chunk_id!r}")
    return artifact_id, int(ordinal_str)


def score_from_distance(distance: float) -> float:
    """chunkshop ``query_top_k`` returns ascending cosine distance.

    Map to a descending [0, 1] similarity score: ``clamp(1 - distance)``.
    """
    return max(0.0, min(1.0, 1.0 - distance))

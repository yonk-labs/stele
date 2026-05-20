"""Portable JSONL import/export for artifact stores.

Two formats:

- ``FORMAT_VERSION = 1`` — artifact-only export (existing
  ``write_jsonl`` / ``read_jsonl``); used by :meth:`Stele.export_jsonl`.
- ``FORMAT_VERSION = 2`` — namespace bundle with a ``kind``
  discriminator per line (``artifact`` or ``memory``); used by
  :meth:`Stele.export_namespace` (#8c). The supersession chain on
  memory rows round-trips via ``MemoryRecord.supersedes``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from stele.core.artifact import Artifact, ArtifactRecord
from stele.core.memory_record import MemoryRecord, MemoryScope

FORMAT_VERSION = 1
BUNDLE_FORMAT_VERSION = 2


def write_jsonl(records: list[ArtifactRecord], path: str | Path) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record_to_payload(record), sort_keys=True))
            handle.write("\n")
    return len(records)


def read_jsonl(path: str | Path) -> list[Artifact]:
    artifacts: list[Artifact] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if payload.get("format_version") != FORMAT_VERSION:
                raise ValueError(f"Unsupported JSONL artifact format on line {line_number}")
            artifacts.append(payload_to_artifact(payload))
    return artifacts


def record_to_payload(record: ArtifactRecord) -> dict[str, Any]:
    content_encoding = record.content_encoding
    content: str
    if isinstance(record.content, bytes):
        content = base64.b64encode(record.content).decode("ascii")
        content_encoding = "bytes"
    else:
        content = record.content
    return {
        "format_version": FORMAT_VERSION,
        "artifact_id": record.artifact_id,
        "reference": record.reference,
        "namespace": record.namespace,
        "session_id": record.session_id,
        "content": content,
        "content_encoding": content_encoding,
        "content_type": record.content_type,
        "metadata": record.metadata,
        "summary": record.summary,
        "raw_summary": record.raw_summary,
        "digest_sha256": record.digest_sha256,
        "byte_size": record.byte_size,
        "token_estimate": record.token_estimate,
        "lifecycle": record.lifecycle,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def payload_to_artifact(payload: dict[str, Any]) -> Artifact:
    content: str | bytes
    if payload["content_encoding"] == "bytes":
        content = base64.b64decode(payload["content"].encode("ascii"))
    else:
        content = payload["content"]
    return Artifact(
        artifact_id=payload["artifact_id"],
        reference=payload["reference"],
        namespace=payload["namespace"],
        session_id=payload["session_id"],
        content=content,
        content_encoding=payload["content_encoding"],
        content_type=payload["content_type"],
        metadata=payload["metadata"],
        summary=payload["summary"],
        raw_summary=payload["raw_summary"],
        digest_sha256=payload["digest_sha256"],
        byte_size=payload["byte_size"],
        token_estimate=payload["token_estimate"],
        lifecycle=payload["lifecycle"],
        expires_at=payload["expires_at"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
    )


# --- Namespace bundle (v2) — used by Stele.export_namespace (#8c) ---


def memory_to_payload(record: MemoryRecord) -> dict[str, Any]:
    return {
        "format_version": BUNDLE_FORMAT_VERSION,
        "kind": "memory",
        "id": record.id,
        "text": record.text,
        "kind_": record.kind,  # collision with discriminator; suffix the field
        "scope": {
            "user_id": record.scope.user_id,
            "agent_id": record.scope.agent_id,
            "app_id": record.scope.app_id,
            "session_id": record.scope.session_id,
            "namespace": record.scope.namespace,
        },
        "source_refs": list(record.source_refs),
        "source_chunk_ids": list(record.source_chunk_ids),
        "confidence": record.confidence,
        "status": record.status,
        "supersedes": list(record.supersedes),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "effective_from": (
            record.effective_from.isoformat() if record.effective_from else None
        ),
        "effective_until": (
            record.effective_until.isoformat() if record.effective_until else None
        ),
        "metadata": dict(record.metadata),
        "pii_flags": list(record.pii_flags),
    }


def payload_to_memory(payload: dict[str, Any]) -> MemoryRecord:
    from datetime import datetime

    scope = payload["scope"]
    created_at = datetime.fromisoformat(payload["created_at"])
    effective_from_raw = payload.get("effective_from")
    effective_from = (
        datetime.fromisoformat(effective_from_raw) if effective_from_raw else created_at
    )
    return MemoryRecord(
        id=payload["id"],
        text=payload["text"],
        kind=payload["kind_"],
        scope=MemoryScope(
            user_id=scope.get("user_id"),
            agent_id=scope.get("agent_id"),
            app_id=scope.get("app_id"),
            session_id=scope.get("session_id"),
            namespace=scope.get("namespace", "default"),
        ),
        source_refs=payload.get("source_refs", []),
        source_chunk_ids=payload.get("source_chunk_ids", []),
        confidence=payload.get("confidence", 1.0),
        status=payload.get("status", "active"),
        supersedes=payload.get("supersedes", []),
        created_at=created_at,
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        effective_from=effective_from,
        effective_until=(
            datetime.fromisoformat(payload["effective_until"])
            if payload.get("effective_until") else None
        ),
        metadata=payload.get("metadata", {}),
        pii_flags=payload.get("pii_flags", []),
    )


def write_namespace_bundle(
    artifacts: list[ArtifactRecord],
    memories: list[MemoryRecord],
    path: str | Path,
) -> int:
    """Write a v2 mixed-record bundle. Returns total line count."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for artifact in artifacts:
            payload = record_to_payload(artifact)
            payload["format_version"] = BUNDLE_FORMAT_VERSION
            payload["kind"] = "artifact"
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
        for memory in memories:
            handle.write(json.dumps(memory_to_payload(memory), sort_keys=True))
            handle.write("\n")
    return len(artifacts) + len(memories)


def read_namespace_bundle(
    path: str | Path,
) -> tuple[list[Artifact], list[MemoryRecord]]:
    artifacts: list[Artifact] = []
    memories: list[MemoryRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if payload.get("format_version") != BUNDLE_FORMAT_VERSION:
                raise ValueError(
                    f"Unsupported bundle format on line {line_number} — "
                    f"expected v{BUNDLE_FORMAT_VERSION}"
                )
            kind = payload.get("kind")
            if kind == "artifact":
                artifacts.append(payload_to_artifact(payload))
            elif kind == "memory":
                memories.append(payload_to_memory(payload))
            else:
                raise ValueError(
                    f"Unknown record kind {kind!r} on line {line_number}"
                )
    return artifacts, memories

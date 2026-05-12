"""Portable JSONL import/export for artifact stores."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from stele.core.artifact import Artifact, ArtifactRecord

FORMAT_VERSION = 1


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

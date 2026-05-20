"""Stele.export_namespace + Stele.import_namespace — #8c."""

from __future__ import annotations

from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope


def _stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )


def test_export_namespace_writes_artifacts_and_memory(tmp_path: Path) -> None:
    s = _stele(tmp_path)
    ns = "exp_ns"
    s.store("artifact one", namespace=ns)
    s.store("artifact two", namespace=ns)
    s.memory.add(
        text="fact one",
        kind="fact",
        source_refs=[f"stele://{ns}/a"],
        scope=MemoryScope(namespace=ns),
    )

    out = tmp_path / "bundle.jsonl"
    result = s.export_namespace(ns, out)

    assert result.exported_count == 3  # 2 artifacts + 1 memory
    assert out.exists()
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 3
    # Each line is JSON with a kind discriminator
    import json
    kinds = [json.loads(ln)["kind"] for ln in lines]
    assert kinds.count("artifact") == 2
    assert kinds.count("memory") == 1
    s.close()


def test_export_namespace_excludes_other_namespaces(tmp_path: Path) -> None:
    s = _stele(tmp_path)
    s.store("in", namespace="target")
    s.store("out", namespace="other")
    out = tmp_path / "bundle.jsonl"
    result = s.export_namespace("target", out)
    assert result.exported_count == 1
    s.close()


def test_export_namespace_rejects_empty(tmp_path: Path) -> None:
    s = _stele(tmp_path)
    with pytest.raises(ValueError):
        s.export_namespace("", tmp_path / "x.jsonl")
    s.close()


def test_round_trip_preserves_supersession_chain(tmp_path: Path) -> None:
    """Export → purge → import preserves the supersedes edge."""
    s1 = _stele(tmp_path)
    ns = "rt_ns"
    s1.store("doc one", namespace=ns)
    older = s1.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=[f"stele://{ns}/a"],
        scope=MemoryScope(namespace=ns),
    )
    s1.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=[f"stele://{ns}/b"],
        scope=MemoryScope(namespace=ns),
        supersedes=[older.record.id],
    )
    bundle = tmp_path / "bundle.jsonl"
    s1.export_namespace(ns, bundle)
    s1.close()

    # Restore into a fresh Stele
    s2 = _stele(tmp_path)
    s2.import_namespace(bundle)
    restored = s2.memory.list(
        MemoryScope(namespace=ns),
        status_filter=["active", "superseded", "retracted", "disputed", "deleted"],
    )
    # Two memory rows survived, including the superseded one with its
    # original id and supersedes edge intact.
    by_id = {m.id: m for m in restored}
    assert older.record.id in by_id
    superseded = by_id[older.record.id]
    assert superseded.status == "superseded"
    # The newer row carries the supersedes pointer to older.id.
    newer_rows = [m for m in restored if m.id != older.record.id]
    assert len(newer_rows) == 1
    assert older.record.id in newer_rows[0].supersedes
    s2.close()


def test_round_trip_preserves_artifact_content(tmp_path: Path) -> None:
    s1 = _stele(tmp_path)
    ns = "content_ns"
    stored = s1.store("the exact bytes we expect to round-trip", namespace=ns)
    bundle = tmp_path / "bundle.jsonl"
    s1.export_namespace(ns, bundle)
    s1.close()

    s2 = _stele(tmp_path)
    s2.import_namespace(bundle)
    fetched = s2.fetch(stored.reference, raw=True)
    assert fetched.content == "the exact bytes we expect to round-trip"
    s2.close()


def test_import_namespace_rejects_v1_artifact_jsonl(tmp_path: Path) -> None:
    """Defensive: import_namespace expects v2 bundle; v1 artifact-only
    JSONL should not silently 'work' with missing memory."""
    s = _stele(tmp_path)
    s.store("only artifact", namespace="ns")
    v1_path = tmp_path / "v1.jsonl"
    s.export_jsonl(v1_path, namespace="ns")
    with pytest.raises(ValueError, match="bundle format"):
        s.import_namespace(v1_path)
    s.close()

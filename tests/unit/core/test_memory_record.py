"""Tests for MemoryRecord model (SC-010 source_refs validation)."""

from datetime import UTC, datetime

import pytest

from stele.core.exceptions import ValidationError
from stele.core.memory_record import (
    MemoryRecord,
    MemoryScope,
    canonical_scope_key,
    memory_text_hash,
)


def _record(**overrides):
    base = dict(
        id="m1",
        text="user prefers Helix editor",
        kind="preference",
        scope=MemoryScope(user_id="alice"),
        source_refs=["stele://default/abc"],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return MemoryRecord(**base)


def test_memory_record_defaults_active_no_expiry():
    r = _record()
    assert r.status == "active"
    assert r.effective_until is None
    assert r.supersedes == []
    assert r.confidence == 1.0


def test_memory_record_rejects_empty_source_refs():
    with pytest.raises(ValidationError) as exc:
        _record(source_refs=[])
    assert "stele://" in str(exc.value)


def test_memory_record_rejects_non_stele_source_ref():
    with pytest.raises(ValidationError) as exc:
        _record(source_refs=["https://example.com/doc"])
    assert "stele://" in str(exc.value)


def test_memory_record_accepts_multiple_source_refs():
    r = _record(source_refs=["stele://ns/a", "stele://ns/b"])
    assert len(r.source_refs) == 2


def test_canonical_scope_key_is_stable():
    s1 = MemoryScope(user_id="alice", namespace="default")
    s2 = MemoryScope(namespace="default", user_id="alice")
    assert canonical_scope_key(s1) == canonical_scope_key(s2)


def test_memory_text_hash_differs_on_text_or_scope_change():
    s = MemoryScope(user_id="alice")
    h1 = memory_text_hash("hello", s)
    h2 = memory_text_hash("hello", MemoryScope(user_id="bob"))
    h3 = memory_text_hash("hi", s)
    assert h1 != h2
    assert h1 != h3

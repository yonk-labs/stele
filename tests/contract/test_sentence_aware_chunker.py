"""SC: sentence_aware chunker — full-sentence boundaries (no mid-sentence cuts)
+ optional neighbor-window context. sqlite + postgres (DSN-gated)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from stele import Stele

_TEXT = (
    "Caroline went to the LGBTQ support group on 7 May. It was powerful. "
    "Melanie painted a lake sunrise last year. She loves nature deeply. "
    "They discussed identity and art at length. Caroline is studying psychology. "
    "Melanie runs charity races for mental health. Both enjoy creative outlets."
)


def _backends() -> list[str]:
    bk = ["sqlite"]
    if os.environ.get("STELE_PG_DSN"):
        bk.append("postgres")
    return bk


def _stash(backend: str, tmp_path: Path, window: int) -> Stele:
    idx = {
        "indexing": {
            "mode": "sync", "provider": "chunkshop", "chunker": "sentence_aware",
            "sentence_max_chars": 120, "sentence_min_chars": 40,
            "neighbor_window": window,
        },
        "retrieval": {"default_mode": "hybrid"},
    }
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "s.db")}, **idx})
    return Stele.from_config(
        {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}, **idx})


@pytest.mark.parametrize("backend", _backends())
def test_sentence_aware_no_midsentence_cuts(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, tmp_path, window=0)
    ns = f"sa_{uuid.uuid4().hex[:8]}"
    stored = stash.store(_TEXT, namespace=ns)
    hits = stash.query(ns, "what did Melanie paint", limit=5, mode="hybrid")
    assert hits, f"{backend}: no hits"
    for h in hits:
        t = h.text.strip()
        # every chunk ends on a sentence terminator — never mid-sentence
        assert t.endswith((".", "!", "?")), f"{backend}: mid-sentence cut: {t!r}"
        assert h.artifact_id == stored.artifact_id
    stash.close()


@pytest.mark.parametrize("backend", _backends())
def test_neighbor_window_adds_context(backend: str, tmp_path: Path) -> None:
    # window=1 chunks should be at least as long as window=0 (they absorb neighbors)
    narrow = _stash(backend, tmp_path / "a", window=0)
    wide = _stash(backend, tmp_path / "b", window=1)
    ns = f"nw_{uuid.uuid4().hex[:8]}"
    narrow.store(_TEXT, namespace=ns)
    wide.store(_TEXT, namespace=ns)
    qn = narrow.query(ns, "Melanie sunrise", limit=1, mode="hybrid")
    qw = wide.query(ns, "Melanie sunrise", limit=1, mode="hybrid")
    assert qn and qw
    assert len(qw[0].text) >= len(qn[0].text), f"{backend}: neighbor window did not add context"
    narrow.close()
    wide.close()

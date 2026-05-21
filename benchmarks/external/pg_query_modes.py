"""Postgres retrieval-mode demonstration — ingest once, query in keyword /
vector / hybrid modes.

Two findings the main matrix sweep cannot show:

1. The main external harness routes through `Stele.recall()` →
   `MemorySearchStrategy` → `MemoryStore.search_with_score`, which is pure
   tsvector regardless of `indexing` / `retrieval.default_mode`. So the
   chunking + hybrid profiles tie the keyword profile on the matrix.
2. The chunk-index path IS exercised by `Stele.query(namespace, query,
   mode=...)` — calling it directly shows the mode-sensitivity.

This script ingests one corpus (MultiHop-RAG and LongBench tasks) once per
chunk-size config, then issues each query three times — once per mode —
and emits a small JSON + Markdown report that documents the actual chunk
+ mode levers.
"""

from __future__ import annotations

import argparse
import contextlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.external import harness, loaders
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele

ARTIFACT_DSN = "postgresql://yonk:yonk@localhost:55432/stele"


def _config(chunk_words: int, chunk_overlap: int) -> dict[str, Any]:
    return {
        "backend": {"type": "postgres", "dsn": ARTIFACT_DSN},
        "indexing": {
            "mode": "sync", "provider": "chunkshop",
            "chunk_words": chunk_words, "chunk_overlap_words": chunk_overlap,
            "hybrid_method": "rrf", "hybrid_rrf_k": 60,
        },
        "retrieval": {"default_mode": "hybrid"},
    }


def _mhr_corpus(
    s: Stele, max_docs: int, ns: str
) -> tuple[MemoryScope, list[tuple[str, str, list[str]]]]:
    """Ingest MHR corpus via ``s.store()`` (the chunk-index path) and return
    (scope, queries).

    Critical: this lane uses ``Stele.store()`` — NOT ``Stele.memory.add()`` —
    because chunkshop indexing is only triggered by store() (see
    stash.py:386 ``self.indexer.submit(record)``). The main external
    harness writes via ``memory.add()`` so chunkshop never receives the
    content, which is why the matrix's chunk-variant profiles all tie.

    queries is [(question, answer, gold_titles)] for scoring.
    """
    queries, corpus = loaders.load_multihoprag()
    scope = MemoryScope(namespace=ns)
    title_to_ref: dict[str, str] = {}
    for doc in corpus[:max_docs]:
        title = doc.get("title", "")
        body = (title + ". " + doc.get("body", ""))[:1500]
        result = s.store(content=body, namespace=ns, metadata={"title": title})
        title_to_ref[title] = result.reference
    out: list[tuple[str, str, list[str]]] = []
    for q in queries[:50]:
        if q.get("question_type") == "null_query":
            continue
        gold = [
            title_to_ref.get(e.get("title", ""), "")
            for e in q.get("evidence_list", []) or []
        ]
        out.append(
            (str(q.get("query", "")), str(q.get("answer", "")), [g for g in gold if g])
        )
    return scope, out


def _score(
    s: Stele,
    scope: MemoryScope,
    queries: Iterable[tuple[str, str, list[str]]],
    mode: str,
    k: int,
) -> dict[str, Any]:
    ans_hit = ev_hit = total = 0
    for question, answer, gold_refs in queries:
        hits = s.query(
            namespace=scope.namespace, query=question, limit=k, mode=mode,
        )
        total += 1
        ctx = " ".join(str(h.text) for h in hits)
        if harness._answer_hit(answer, ctx):
            ans_hit += 1
        if any(h.reference in gold_refs for h in hits):
            ev_hit += 1
    return {
        "mode": mode,
        "queries": total,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(total, 1), 1),
        "evidence_recall_at_k_pct": round(100 * ev_hit / max(total, 1), 1),
    }


def _run_config(chunk_words: int, chunk_overlap: int, k: int) -> dict[str, Any]:
    cfg = _config(chunk_words, chunk_overlap)
    ns = f"qmodes-mhr-{chunk_words}-{chunk_overlap}"
    s = Stele.from_config(cfg)
    # Cleanup any prior atoms under this namespace so re-runs are stable.
    with contextlib.suppress(Exception):
        s.purge_namespace(ns)
    scope, queries = _mhr_corpus(s, max_docs=80, ns=ns)
    per_mode = [_score(s, scope, queries, m, k) for m in ("keyword", "vector", "hybrid")]
    s.close()
    return {
        "chunk_words": chunk_words,
        "chunk_overlap_words": chunk_overlap,
        "k": k,
        "per_mode": per_mode,
    }


def _md(report: dict[str, Any]) -> str:
    rows = report["chunk_configs"]
    modes = ("keyword", "vector", "hybrid")
    out = [
        "# Postgres retrieval-mode demonstration (Stele.query direct)",
        "",
        f"Generated: {report['timestamp']}",
        "",
        "This is the **direct `Stele.query()` lane** — bypasses "
        "`Stele.recall()` and exercises the chunk-index dispatch in "
        "`stash.py:587`. Same corpus (MultiHop-RAG, 80 documents), same "
        "queries, three retrieval modes, three chunk sizes.",
        "",
        "| chunk_words / overlap | "
        + " | ".join(f"answer_span% ({m})" for m in modes)
        + " | "
        + " | ".join(f"evidence% ({m})" for m in modes)
        + " |",
        "|" + "---|" * (1 + 2 * len(modes)),
    ]
    for cfg in rows:
        per = {m["mode"]: m for m in cfg["per_mode"]}
        ans = " | ".join(
            str(per[m]["answer_span_recall_at_k_pct"]) for m in modes
        )
        ev = " | ".join(
            str(per[m]["evidence_recall_at_k_pct"]) for m in modes
        )
        out.append(
            f"| {cfg['chunk_words']} / {cfg['chunk_overlap_words']} | "
            f"{ans} | {ev} |"
        )
    out.append("")
    out.append(
        "Comparison to the recall-lane matrix: in the matrix, "
        "`pg-keyword`, `pg-vector`, and `pg-hybrid` produce identical "
        "numbers because `recall` → `memory_search` → "
        "`MemoryStore.search_with_score` is tsvector-only regardless of "
        "`retrieval.default_mode`. The chunk-index path is wired but "
        "only `Stele.search()` and `Stele.query()` consult it today."
    )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument(
        "--output-root", type=Path, default=Path("benchmarks/runs")
    )
    args = ap.parse_args()
    configs = [(120, 30), (220, 60), (400, 80)]
    chunk_configs = [
        _run_config(cw, co, k=args.k) for cw, co in configs
    ]
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "k": args.k,
        "chunk_configs": chunk_configs,
    }
    out_dir = args.output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Postgres-Query-Modes.json").write_text(
        json.dumps(report, indent=2)
    )
    (out_dir / "Postgres-Query-Modes.md").write_text(_md(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""Full controlled sweep: chunker x retrieval x packing x hints, with jscore+MRR+latency.

Controlled sweeps from baseline (sentence_aware + hybrid + raw + query-hints), so
every axis is covered without the 144-lane cross product:

  A  chunker x packing   (hybrid):  {fixed_overlap, sentence_aware, consolidation, enriching} x {raw, digest, facts}
  B  retrieval x packing (sentence_aware): {keyword, cascade_a, cascade_b} x {raw, digest, facts}
  C  hints               (sentence_aware, hybrid): {none, expanded} x {digest, facts}
  + raw_fetch ceiling

Per (lane, question): correct (jscore gemma@133) | mrr (1/rank of first chunk with the
gold answer) | retr_ms | pack_ms | ans_ms | ctx_chars. All post-fix (promoted defaults
+ stopword/snippet/PII fixes). Answerer qwen@193.

Run: STELE_PG_DSN=... OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.sweep_matrix --per-corpus 40
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import lede

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_shootout import _answer, _lanes
from benchmarks.external.consolidators import extractive
from benchmarks.external.cross_corpus_matrix import _units
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_STOP = {"what", "when", "where", "who", "did", "does", "is", "are", "the", "a", "an",
         "to", "of", "in", "on", "for", "her", "his", "their", "would", "be", "likely", "how", "was"}


def _store(dsn: str, chunker: str) -> Stele:
    idx = dict(mode="sync", provider="chunkshop")
    if chunker == "fixed_overlap":
        idx.update(chunker="fixed_overlap")
    elif chunker == "sentence_aware":
        idx.update(chunker="sentence_aware", sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1)
    elif chunker == "consolidation":
        idx.update(chunker="consolidation", consolidator_module="benchmarks.external.consolidators.extractive",
                   consolidator_kwargs={"max_facts": 60, "date_mode": "both"}, fact_max_chars=200)
    elif chunker == "enriching":
        idx.update(chunker="consolidation", consolidator_module="benchmarks.external.consolidators.enriching",
                   consolidator_kwargs={"max_facts": 1000, "date_mode": "both"}, fact_max_chars=1000)
    return Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn),
                                    indexing=IndexingConfig(**idx),
                                    retrieval=RetrievalConfig(default_mode="hybrid")))


def _clear(st: Stele, ns: str) -> None:
    try:
        for h in st.list(namespace=ns, limit=100_000).items:
            st.delete(h.reference)
    except Exception:
        pass


def _hints(q: str, mode: str) -> list[str]:
    if mode == "none":
        return ["__nohints__"]
    if mode == "query":
        return [q]
    words = [w for w in re.findall(r"[A-Za-z]+", q) if w.lower() not in _STOP and len(w) > 2]
    try:
        import lede_spacy
        out = lede_spacy.expand_hints(words, kinds=("synonyms",), top_k=3)
        return list(out) if out else (words or [q])
    except Exception:
        return words or [q]


def _pack(packing: str, chunks: list[str], q: str, hints_mode: str) -> str:
    if packing == "raw":
        return "\n\n".join(chunks)
    if not chunks:
        return ""
    rep = lede.readable_report("\n\n".join(chunks), hints=_hints(q, hints_mode)).to_markdown()
    top5 = "\n\n---\n\n".join(chunks[:5])
    base = f"{rep}\n\n## Retrieved Chunks\n\n{top5}"
    if packing == "digest":
        return base
    out = extractive.consolidate("\n\n".join(chunks), date_mode="both", max_facts=12)
    facts = "\n".join(f"- {f['support_span']}" for f in out["facts"])
    return f"{base}\n\n## Facts\n\n{facts}"


def _rr(chunks: list[str], gold: str) -> float:
    """Reciprocal rank of the first relevant chunk. Short gold (a fact/date/name):
    substring match. Long gold (a generated response): >=50% content-word overlap."""
    g = (gold or "").strip().lower()
    if not g:
        return 0.0
    if len(g) <= 60:
        def rel(c: str) -> bool:
            return g in c.lower()
    else:
        terms = {w for w in re.findall(r"[a-z0-9]+", g) if w not in _STOP and len(w) > 2}
        def rel(c: str) -> bool:
            if not terms:
                return False
            ct = set(re.findall(r"[a-z0-9]+", c.lower()))
            return len(terms & ct) / len(terms) >= 0.5
    for i, c in enumerate(chunks):
        if rel(c):
            return 1.0 / (i + 1)
    return 0.0


def _retrieve(stores, refs, unit_id, q, ch, rt, cache):
    if (ch, rt) in cache:
        return cache[(ch, rt)]
    st, ref = stores[ch], refs[ch][unit_id]
    t = time.perf_counter()
    if rt == "hybrid":
        chunks = [h.text for h in st.search(ref, q, limit=10, mode="hybrid")]
    elif rt == "keyword":
        chunks = [h.text for h in st.search(ref, q, limit=10, mode="keyword")]
    else:  # cascade_a / cascade_b
        chunks = _lanes(st, ref, q)[rt]
    cache[(ch, rt)] = (chunks, (time.perf_counter() - t) * 1000)
    return cache[(ch, rt)]


def _build_lanes() -> list[tuple[str, str, str, str, str]]:
    """(lane, chunker, retrieval, packing, hints)."""
    lanes = []
    for ch in ["fixed_overlap", "sentence_aware", "consolidation", "enriching"]:
        for pk in ["raw", "digest", "facts"]:
            lanes.append((f"A:{ch}+{pk}", ch, "hybrid", pk, "query"))
    for rt in ["keyword", "cascade_a", "cascade_b"]:
        for pk in ["raw", "digest", "facts"]:
            lanes.append((f"B:{rt}+{pk}", "sentence_aware", rt, pk, "query"))
    for hn in ["none", "expanded"]:
        for pk in ["digest", "facts"]:
            lanes.append((f"C:hints-{hn}+{pk}", "sentence_aware", "hybrid", pk, hn))
    lanes.append(("raw_fetch", "sentence_aware", "raw_fetch", "raw", "none"))
    return lanes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--corpora", nargs="+", default=["locomo", "ragbench-hotpotqa", "ragbench-covidqa"])
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cross-corpus"))
    args = ap.parse_args()
    dsn = os.environ["STELE_PG_DSN"]

    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec); spec.loader.exec_module(rj)
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_GEMMA,
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="http://192.168.1.133:8000/v1", judge_api_key="local")
    judge = OpenAICompatAnswerer(answer_model=_GEMMA, judge_model=_GEMMA,
                                 base_url="http://192.168.1.133:8000/v1", api_key="local")

    lanes = _build_lanes()
    chunkers = sorted({ch for _, ch, _, _, _ in lanes})
    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        units = _units(corpus, args.per_corpus)
        stores = {ch: _store(dsn, ch) for ch in chunkers}
        refs: dict[str, dict[str, str]] = {ch: {} for ch in chunkers}
        for ch, st in stores.items():
            _clear(st, f"sweep-{ch}-{corpus}")
        done = 0
        for unit_id, content, qas in units:
            for ch, st in stores.items():
                refs[ch][unit_id] = st.store(content, namespace=f"sweep-{ch}-{corpus}").reference
            for q, gold in qas:
                retr_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
                rec = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for lane, ch, rt, pk, hn in lanes:
                    if rt == "raw_fetch":
                        ctx, mrr, rms, pms = content, _rr([content], gold), 0.0, 0.0
                    else:
                        chunks, rms = _retrieve(stores, refs, unit_id, q, ch, rt, retr_cache)
                        mrr = _rr(chunks, gold)
                        tp = time.perf_counter(); ctx = _pack(pk, chunks, q, hn); pms = (time.perf_counter() - tp) * 1000
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rec["lanes"][lane] = {"correct": correct, "mrr": round(mrr, 4), "retr_ms": round(rms, 1),
                                          "pack_ms": round(pms, 1), "ans_ms": round(ams, 1), "ctx_chars": len(ctx)}
                rows.append(rec)
                done += 1
                if done % 3 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        for st in stores.values():
            st.close()
        print(f"[{corpus}] done", flush=True)

    agg: dict[str, dict[str, dict[str, float]]] = {}
    for corpus in args.corpora:
        crows = [r for r in rows if r["corpus"] == corpus]
        agg[corpus] = {}
        for lane, *_ in lanes:
            vals = [r["lanes"][lane] for r in crows if lane in r["lanes"]]
            if not vals:
                continue
            k = len(vals)
            agg[corpus][lane] = {
                "jscore": round(sum(v["correct"] for v in vals) / k, 3),
                "mrr": round(sum(v["mrr"] for v in vals) / k, 3),
                "retr_ms": round(sum(v["retr_ms"] for v in vals) / k, 1),
                "ans_ms": round(sum(v["ans_ms"] for v in vals) / k, 1),
                "ctx_chars": int(sum(v["ctx_chars"] for v in vals) / k),
                "n": k}

    print("\n=== SWEEP MATRIX (jscore | mrr | retr_ms | ans_ms | ctx) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for lane in sorted(agg[corpus], key=lambda x: -agg[corpus][x]["jscore"]):
            a = agg[corpus][lane]
            print(f"  {lane:26s} js={a['jscore']:.2f} mrr={a['mrr']:.2f} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f} ctx={a['ctx_chars']:6d}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"sweep-matrix-{stamp}.json"
    f.write_text(json.dumps({"config": "post-fix / chunker x retrieval x packing x hints / jscore+mrr+latency",
                             "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

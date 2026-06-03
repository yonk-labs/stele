# ruff: noqa: E501,SIM115,SIM105,E702  -- benchmark helper.
"""Why did memory recall lose to RAG? Isolate engine vs representation.

The memory-recall lane showed memory-store recall losing badly to document RAG
on LoCoMo. This matrix tells us WHY by crossing two axes on the SAME questions,
same judge, same answerer:

  population  x  engine
  ----------     ------
  raw_doc        chunk-hybrid   -> doc_rag          (the baseline that won)
  fragments      memory-hybrid  -> mem_fragment     (the naive memory path that lost)
  extracted      chunk-hybrid   -> facts_to_chunks  (option-b: facts in the index you already run)
  extracted      memory-hybrid  -> mem_extracted    (memory done right: extract, then recall)

Reads:
  doc_rag        vs mem_extracted   = does a real memory path beat RAG at all?
  facts_to_chunks vs mem_extracted  = does the memory ENGINE earn its keep vs the chunk engine, same facts?
  mem_fragment   vs mem_extracted   = does proper extraction rescue memory recall (representation)?
  doc_rag        vs facts_to_chunks = raw doc vs extracted facts, same engine?

Memory recall is scoped per-unit via source_ref_filter, so it is fair against
ref-scoped chunk retrieval. Additive: writes to benchmarks/runs/cq-additive/.

Run: STELE_PG_DSN=... .venv/bin/python -m benchmarks.external.memory_vs_rag_matrix --per-corpus 40
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

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cross_corpus_matrix import _units
from benchmarks.external.sweep_matrix import _GEMMA, _QWEN, _answer, _rr
from stele.core.config import (
    BackendConfig,
    IndexingConfig,
    RetrievalConfig,
    StashConfig,
)
from stele.core.memory_record import AddRequest, MemoryScope
from stele.core.stash import Stele

_SEG_CAP = 150


def _segments(content: str, cap: int = _SEG_CAP) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+|\n+", content)
    segs: list[str] = []
    seen: set[str] = set()
    for s in raw:
        s = s.strip()
        key = s.lower()
        if 15 <= len(s) <= 400 and key not in seen:
            seen.add(key); segs.append(s)
        if len(segs) >= cap:
            break
    return segs


def _store_full(dsn: str) -> Stele:
    # One Stele does both jobs: chunk indexing for the chunk-engine lanes AND a
    # vector-enabled memory store for the memory-engine lanes.
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1),
        retrieval=RetrievalConfig(default_mode="hybrid", memory_vector=True),
    ))


_LANES = ("doc_rag", "mem_fragment", "facts_to_chunks", "mem_extracted")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--corpora", nargs="+", default=["locomo"])
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cq-additive"))
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

    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        st = _store_full(dsn)
        ns_doc, ns_facts = f"mvr-doc-{corpus}", f"mvr-facts-{corpus}"
        ns_frag, ns_ext = f"mvr-frag-{corpus}", f"mvr-ext-{corpus}"
        for ns in (ns_doc, ns_facts, ns_frag, ns_ext):
            try:
                st.purge_namespace(ns)
            except Exception:
                pass

        units = list(_units(corpus, args.per_corpus))
        refs: dict[str, tuple[str, str]] = {}  # unit_id -> (ref_doc, ref_facts)
        t_pop = time.perf_counter()
        for unit_id, content, _qas in units:
            stored = st.store(content, namespace=ns_doc)
            ref_doc = stored.reference
            # extracted facts -> memory store (mem_extracted population), collect texts
            report = st.extract.from_artifact(
                artifact_id=stored.reference, scope=MemoryScope(namespace=ns_ext)
            )
            extracted = [a.candidate.text for a in report.accepted] or [content]
            ref_facts = st.store("\n".join(extracted), namespace=ns_facts).reference
            # raw fragments -> memory store (mem_fragment population)
            segs = _segments(content)
            if segs:
                st.memory.add_many([
                    AddRequest(text=s, kind="fact", source_refs=[ref_doc],
                               scope=MemoryScope(namespace=ns_frag))
                    for s in segs
                ])
            refs[unit_id] = (ref_doc, ref_facts)
        print(f"[{corpus}] populated {len(units)} units in {(time.perf_counter()-t_pop):.1f}s", flush=True)

        done = 0
        for unit_id, _content, qas in units:
            ref_doc, ref_facts = refs[unit_id]
            for q, gold in qas:
                ctxs: dict[str, tuple[str, float, float]] = {}  # lane -> (ctx, mrr, retr_ms)
                # chunk-engine lanes
                for lane, ref in (("doc_rag", ref_doc), ("facts_to_chunks", ref_facts)):
                    tr = time.perf_counter()
                    chunks = [h.text for h in st.search(ref, q, limit=10, mode="hybrid")]
                    rms = (time.perf_counter() - tr) * 1000
                    ctxs[lane] = ("\n\n".join(chunks), _rr(chunks, gold), rms)
                # memory-engine lanes (scoped to this unit via source_ref_filter)
                for lane, ns in (("mem_fragment", ns_frag), ("mem_extracted", ns_ext)):
                    tr = time.perf_counter()
                    hits = st.memory.search_with_score(q, MemoryScope(namespace=ns),
                                                       limit=10, source_ref_filter=ref_doc)
                    rms = (time.perf_counter() - tr) * 1000
                    texts = [h.record.text for h in hits]
                    ctxs[lane] = ("\n".join(texts), _rr(texts, gold), rms)

                rec = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for lane in _LANES:
                    ctx, mrr, rms = ctxs[lane]
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rec["lanes"][lane] = {"correct": correct, "mrr": round(mrr, 4),
                                          "retr_ms": round(rms, 1), "ans_ms": round(ams, 1),
                                          "ctx_chars": len(ctx)}
                rows.append(rec)
                done += 1
                if done % 5 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        st.close()
        print(f"[{corpus}] done", flush=True)

    agg: dict[str, dict[str, dict[str, float]]] = {}
    for corpus in args.corpora:
        crows = [r for r in rows if r["corpus"] == corpus]
        agg[corpus] = {}
        for lane in _LANES:
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

    print("\n=== MEMORY vs RAG MATRIX (population x engine) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for lane in sorted(agg[corpus], key=lambda x: -agg[corpus][x]["jscore"]):
            a = agg[corpus][lane]
            print(f"  {lane:16s} js={a['jscore']:.3f} mrr={a['mrr']:.3f} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f} ctx={a['ctx_chars']:6d} n={a['n']}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"memory-vs-rag-{stamp}.json"
    f.write_text(json.dumps({"config": "population x engine: why memory recall lost to RAG", "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

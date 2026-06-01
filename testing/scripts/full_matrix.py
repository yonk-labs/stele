# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""Full cross-corpus strategy matrix (postgres / pgvector) — no single-domain assumptions.

Every retrieval architecture x every packing, plus the enrichment substrate and the
raw_fetch ceiling, across three domains (conversational / multi-hop / biomedical).

  retrieval (sentence_aware substrate): keyword | cascade_a (fts->sem) |
                                        cascade_b (sem->fts) | hybrid (RRF)
  packing:                              raw | digest | facts (digest+facts)
  enrichment substrate (consolidation chunker + enriching consolidator): raw | facts
  raw_fetch:                            full document (ceiling)

= 4*3 + 2 + 1 = 15 lanes. Answerer qwen@193, judge gemma@133 (verbatim jscore).
Inputs are the SAME units the stele cross-corpus + mem0 lanes use (units.json
shape via _units), so all three are comparable.

Run:  STELE_PG_DSN=... OPENAI_API_KEY=local \
      .venv/bin/python -m benchmarks.external.full_matrix --per-corpus 40
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_packing_matrix import _facts, _pack
from benchmarks.external.cascade_shootout import _answer, _lanes
from benchmarks.external.cross_corpus_matrix import _units
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_RETR = ["keyword", "cascade_a", "cascade_b", "hybrid"]
_PACK = ["raw", "digest", "facts"]
_ENR_MODULE = "benchmarks.external.consolidators.enriching"


def _default_store(dsn: str) -> Stele:
    # promoted defaults (sentence_aware + sync + hybrid) come from config now,
    # but pin them explicitly so the harness is self-documenting.
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1),
        retrieval=RetrievalConfig(default_mode="hybrid")))


def _enrichment_store(dsn: str) -> Stele:
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="consolidation",
                                consolidator_module=_ENR_MODULE,
                                consolidator_kwargs={"max_facts": 1000, "date_mode": "both"},
                                fact_max_chars=1000),
        retrieval=RetrievalConfig(default_mode="hybrid")))


def _clear(st: Stele, ns: str) -> None:
    try:
        for h in st.list(namespace=ns, limit=100_000).items:
            st.delete(h.reference)
    except Exception:
        pass


def _lane_contexts(st_def: Stele, ref_def: str, st_enr: Stele, ref_enr: str,
                   content: str, q: str) -> dict[str, str]:
    """All 15 lane contexts for one question."""
    casc = _lanes(st_def, ref_def, q)  # {rrf, cascade_a, cascade_b}
    kw = [h.text for h in st_def.search(ref_def, q, limit=10, mode="keyword")]
    retr = {"keyword": kw, "cascade_a": casc["cascade_a"],
            "cascade_b": casc["cascade_b"], "hybrid": casc["rrf"]}
    out: dict[str, str] = {}
    for r, chunks in retr.items():
        for p in _PACK:
            out[f"{r}+{p}"] = _pack(p, chunks, q)
    enr = [h.text for h in st_enr.search(ref_enr, q, limit=10, mode="hybrid")]
    out["enrichment+raw"] = "\n\n".join(enr)
    out["enrichment+facts"] = _facts(enr, q)
    out["raw_fetch"] = content
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--corpora", nargs="+", default=["locomo", "ragbench-hotpotqa", "ragbench-covidqa"])
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cross-corpus"))
    args = ap.parse_args()
    dsn = os.environ["STELE_PG_DSN"]

    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rj)
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_GEMMA,
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="http://192.168.1.133:8000/v1", judge_api_key="local")
    judge = OpenAICompatAnswerer(answer_model=_GEMMA, judge_model=_GEMMA,
                                 base_url="http://192.168.1.133:8000/v1", api_key="local")

    lanes = [f"{r}+{p}" for r in _RETR for p in _PACK] + ["enrichment+raw", "enrichment+facts", "raw_fetch"]
    tally: dict[str, dict[str, dict[str, int]]] = {}
    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        tally[corpus] = {ln: {"ok": 0, "n": 0} for ln in lanes}
        units = _units(corpus, args.per_corpus)
        st_def, st_enr = _default_store(dsn), _enrichment_store(dsn)
        nd, ne = f"fm-def-{corpus}", f"fm-enr-{corpus}"
        _clear(st_def, nd); _clear(st_enr, ne)
        done = 0
        for unit_id, content, qas in units:
            ref_def = st_def.store(content, namespace=nd).reference
            ref_enr = st_enr.store(content, namespace=ne).reference
            for q, gold in qas:
                ctxs = _lane_contexts(st_def, ref_def, st_enr, ref_enr, content, q)
                per = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for ln in lanes:
                    a = _answer(ans, ctxs[ln], q)
                    ok = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    tally[corpus][ln]["ok"] += ok
                    tally[corpus][ln]["n"] += 1
                    per["lanes"][ln] = {"correct": ok}
                rows.append(per)
                done += 1
                if done % 5 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        st_def.close(); st_enr.close()
        best = max(lanes, key=lambda ln: tally[corpus][ln]["ok"])
        print(f"[{corpus}] best={best} {tally[corpus][best]['ok']}/{tally[corpus][best]['n']}", flush=True)

    print("\n=== FULL CROSS-CORPUS MATRIX (15 lanes, promoted defaults, postgres) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for ln in sorted(lanes, key=lambda x: -tally[corpus][x]["ok"]):
            t = tally[corpus][ln]
            acc = t["ok"] / t["n"] if t["n"] else 0.0
            print(f"  {ln:18s} {t['ok']:>3d}/{t['n']:<3d} ({acc:.2f})")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"full-matrix-{stamp}.json"
    f.write_text(json.dumps({"config": "promoted-defaults / 15 lanes / postgres", "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

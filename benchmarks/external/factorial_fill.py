# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""Fill the missing interaction cells the star sweep skipped.

sweep_matrix was a star design (vary one axis from sentence_aware+hybrid+raw), so it
never ran the alternate chunkers against the cascade/keyword retrievers. This runs
exactly that missing block as a full factorial:

  {fixed_overlap, consolidation, enriching} x {keyword, cascade_a, cascade_b} x {raw, digest, facts}

= 27 lanes, n=40/corpus, directional (matches the n=40 sweep family). Lane names are
`D:<chunker>+<retrieval>+<packing>` so consolidate_grid._decode expands them like the
rest. Reuses sweep_matrix's store/retrieve/pack/score helpers verbatim.

Run: STELE_PG_DSN=... OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.factorial_fill --per-corpus 40
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
from benchmarks.external.cascade_shootout import _answer
from benchmarks.external.cross_corpus_matrix import _units
from benchmarks.external.sweep_matrix import _clear, _pack, _retrieve, _rr, _store

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_CHUNKERS = ["fixed_overlap", "consolidation", "enriching"]
_RETRIEVERS = ["keyword", "cascade_a", "cascade_b"]
_PACKINGS = ["raw", "digest", "facts"]


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

    # (lane, chunker, retrieval, packing, hints) — full factorial of the missing block
    lanes = [(f"D:{ch}+{rt}+{pk}", ch, rt, pk, "query")
             for ch in _CHUNKERS for rt in _RETRIEVERS for pk in _PACKINGS]

    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        units = _units(corpus, args.per_corpus)
        stores = {ch: _store(dsn, ch) for ch in _CHUNKERS}
        refs: dict[str, dict[str, str]] = {ch: {} for ch in _CHUNKERS}
        for ch, st in stores.items():
            _clear(st, f"fac-{ch}-{corpus}")
        done = 0
        for unit_id, content, qas in units:
            for ch, st in stores.items():
                refs[ch][unit_id] = st.store(content, namespace=f"fac-{ch}-{corpus}").reference
            for q, gold in qas:
                retr_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
                rec = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for lane, ch, rt, pk, hn in lanes:
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

    agg: dict[str, dict[str, dict[str, Any]]] = {}
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
                "tokens": int(sum(v["ctx_chars"] for v in vals) / k / 4),
                "retr_ms": round(sum(v["retr_ms"] for v in vals) / k, 1),
                "ans_ms": round(sum(v["ans_ms"] for v in vals) / k, 1),
                "n": k}

    print(f"\n=== FACTORIAL FILL (missing chunker x retriever x packing cells, n={args.per_corpus}) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for lane in sorted(agg[corpus], key=lambda x: -agg[corpus][x]["jscore"]):
            a = agg[corpus][lane]
            print(f"  {lane:34s} js={a['jscore']:.2f} tok={a['tokens']:6d} n={a['n']}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"factorial-fill-{stamp}.json"
    f.write_text(json.dumps({"config": "missing interaction cells / chunker x retrieval x packing / n=40", "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

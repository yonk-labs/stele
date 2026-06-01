# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""High-N digest VARIANTS — the digest-family enhancements at n=250.

Complements digest_highn (plain hybrid+digest) and high_n_matrix (hybrid_facts) with
the enhanced digest versions, all at confident N + jscore/tokens/latency:

  digest_expanded     sentence_aware, hybrid, digest, EXPANDED (synonym) hints
  enriching_digest    enriching/enhanced chunker, hybrid, digest
  enriching_facts     enriching/enhanced chunker, hybrid, digest+facts

Run: STELE_PG_DSN=... OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.digest_variants_highn --n 250
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_shootout import _answer
from benchmarks.external.high_n_matrix import _units
from benchmarks.external.sweep_matrix import _clear, _pack, _rr, _store

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
# (lane, chunker, packing, hints)
_LANES = [
    ("digest_expanded", "sentence_aware", "digest", "expanded"),
    ("enriching_digest", "enriching", "digest", "query"),
    ("enriching_facts", "enriching", "facts", "query"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250)
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

    chunkers = sorted({ch for _, ch, _, _ in _LANES})
    rows = []
    for corpus in args.corpora:
        units = _units(corpus, args.n)
        stores = {ch: _store(dsn, ch) for ch in chunkers}
        refs = {ch: {} for ch in chunkers}
        for ch, st in stores.items():
            _clear(st, f"dv-{ch}-{corpus}")
        done = 0
        for uid, content, qas in units:
            for ch, st in stores.items():
                refs[ch][uid] = st.store(content, namespace=f"dv-{ch}-{corpus}").reference
            for q, gold in qas:
                cache = {}
                for lane, ch, pk, hn in _LANES:
                    if ch not in cache:
                        t = time.perf_counter()
                        cache[ch] = ([h.text for h in stores[ch].search(refs[ch][uid], q, limit=10, mode="hybrid")],
                                     (time.perf_counter() - t) * 1000)
                    chunks, rms = cache[ch]
                    ctx = _pack(pk, chunks, q, hn)
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rows.append({"corpus": corpus, "lane": lane, "q": q, "gold": gold, "correct": correct,
                                 "mrr": round(_rr(chunks, gold), 4), "ctx_chars": len(ctx),
                                 "retr_ms": round(rms, 1), "ans_ms": round(ams, 1)})
                done += 1
                if done % 10 == 0:
                    print(f"  {corpus}: {done} done", flush=True)
        for st in stores.values():
            st.close()
        print(f"[{corpus}] done", flush=True)

    from statistics import mean
    print("\n=== HIGH-N DIGEST VARIANTS (n=250) ===")
    agg = {}
    for corpus in args.corpora:
        agg[corpus] = {}
        print(f"\n{corpus}:")
        for lane, *_ in _LANES:
            v = [r for r in rows if r["corpus"] == corpus and r["lane"] == lane]
            if not v:
                continue
            a = {"jscore": round(mean(r["correct"] for r in v), 3), "mrr": round(mean(r["mrr"] for r in v), 3),
                 "tokens": int(mean(r["ctx_chars"] for r in v) / 4), "retr_ms": round(mean(r["retr_ms"] for r in v), 1),
                 "ans_ms": round(mean(r["ans_ms"] for r in v), 1), "n": len(v)}
            agg[corpus][lane] = a
            print(f"  {lane:18s} js={a['jscore']:.3f} mrr={a['mrr']:.2f} tok={a['tokens']:6d} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f} n={a['n']}")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (args.out / f"digest-variants-highn-{stamp}.json").write_text(json.dumps({"agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote digest-variants-highn-{stamp}.json")


if __name__ == "__main__":
    main()

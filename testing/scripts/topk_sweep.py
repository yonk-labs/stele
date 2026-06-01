# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""Top-k sweep: map the accuracy / tokens / latency frontier for the optimization presets.

Holds everything constant (sentence_aware + hybrid + raw chunks, HNSW) and varies only
the number of retrieved chunks fed to the answerer: k in {1,3,5,10,20}. Fewer chunks =
fewer tokens + faster answer, at some accuracy cost — this is the curve the
`token_min` / `fast` / `balanced` / `max_accuracy` presets are read off.

Run: STELE_PG_DSN=... OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.topk_sweep --n 250
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path
from statistics import mean

import lede

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_shootout import _answer
from benchmarks.external.consolidators import extractive
from benchmarks.external.high_n_matrix import _clear, _units
from benchmarks.external.sweep_matrix import _hints, _rr
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_KS = [1, 3, 5, 10, 20]


def _store_nb(dsn: str, neighbor: int) -> Stele:
    """sentence_aware store with neighbor_window = neighbor (1=on overlap, 0=off)."""
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=neighbor, hnsw=True),
        retrieval=RetrievalConfig(default_mode="hybrid")))


def _digest_mix(chunks: list[str], q: str) -> str:
    """The 'buy' kitchen-sink preset: lede digest (expanded hints = enhance)
    + date-resolved facts + top-3 raw chunks. Max-context-mix candidate."""
    if not chunks:
        return ""
    joined = "\n\n".join(chunks)
    rep = lede.readable_report(joined, hints=_hints(q, "expanded")).to_markdown()
    out = extractive.consolidate(joined, date_mode="both", max_facts=12)
    facts = "\n".join(f"- {f['support_span']}" for f in out["facts"])
    top3 = "\n\n---\n\n".join(chunks[:3])
    return f"{rep}\n\n## Facts\n\n{facts}\n\n## Key Excerpts\n\n{top3}"


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

    rows = []
    for corpus in args.corpora:
        units = _units(corpus, args.n)
        stores = {"nb1": _store_nb(dsn, 1), "nb0": _store_nb(dsn, 0)}  # neighbor on/off
        refs = {nb: {} for nb in stores}
        for nb, st in stores.items():
            _clear(st, f"tk-{nb}-{corpus}")
        done = 0
        for uid, content, qas in units:
            for nb, st in stores.items():
                refs[nb][uid] = st.store(content, namespace=f"tk-{nb}-{corpus}").reference
            for q, gold in qas:
                for nb, st in stores.items():
                    t = time.perf_counter()
                    hits = [h.text for h in st.search(refs[nb][uid], q, limit=max(_KS), mode="hybrid")]
                    retr_ms = (time.perf_counter() - t) * 1000
                    variants = [(str(k), hits[:k], "\n\n".join(hits[:k])) for k in _KS]
                    if nb == "nb1":  # digest_mix only needs one substrate
                        variants.append(("mix", hits[:3], _digest_mix(hits, q)))
                    for tag, chunks, ctx in variants:
                        ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                        correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                        rows.append({"corpus": corpus, "neighbor": nb, "k": tag, "correct": correct,
                                     "mrr": round(_rr(chunks, gold), 4), "ctx_chars": len(ctx),
                                     "retr_ms": round(retr_ms, 1), "ans_ms": round(ams, 1)})
                done += 1
                if done % 10 == 0:
                    print(f"  {corpus}: {done} done", flush=True)
        for st in stores.values():
            st.close()
        print(f"[{corpus}] done", flush=True)

    agg = {}
    combos = [("nb1", str(k)) for k in _KS] + [("nb1", "mix")] + [("nb0", str(k)) for k in _KS]
    print("\n=== TOP-K x NEIGHBOR FRONTIER + digest_mix (jscore | tokens | ans_ms) ===")
    for corpus in args.corpora:
        agg[corpus] = {}
        print(f"\n{corpus}:")
        for nb, tag in combos:
            v = [r for r in rows if r["corpus"] == corpus and r["neighbor"] == nb and r["k"] == tag]
            if not v:
                continue
            a = {"jscore": round(mean(r["correct"] for r in v), 3), "mrr": round(mean(r["mrr"] for r in v), 3),
                 "tokens": int(mean(r["ctx_chars"] for r in v) / 4), "retr_ms": round(mean(r["retr_ms"] for r in v), 1),
                 "ans_ms": round(mean(r["ans_ms"] for r in v), 1), "n": len(v)}
            label = "digest_mix" if tag == "mix" else f"{nb}_k={tag}"
            agg[corpus][label] = a
            print(f"  {label:12s} js={a['jscore']:.3f} mrr={a['mrr']:.2f} tok={a['tokens']:6d} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f}")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (args.out / f"topk-sweep-{stamp}.json").write_text(json.dumps({"agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote topk-sweep-{stamp}.json")


if __name__ == "__main__":
    main()

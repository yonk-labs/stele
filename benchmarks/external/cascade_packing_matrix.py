# ruff: noqa: E501,SIM115  -- benchmark helper.
"""9-lane matrix: 3 retrieval architectures x 3 packings (postgres / pgvector).

Crosses the cascade-shootout retrieval lanes with packing variants, across
several LoCoMo conversations, to settle two questions at once:

  retrieval:  rrf | cascade_a (FTS->semantic) | cascade_b (semantic->keyword)
  packing:    raw      concat top-k chunks (no lede)
              digest   lede.readable_report(hints=[q]) + top-5 chunks
              facts    digest + extractive date-resolved facts appended (additive)

Substrate held constant: sentence_aware + bge-base + 1000-char + neighbor=1.
Answerer qwen@193, judge gemma@133 (Mem0 jscore, abstention=wrong) — both local.

Run (background-friendly):
  STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele OPENAI_API_KEY=local \
  .venv/bin/python -m benchmarks.external.cascade_packing_matrix --max-samples 5 --qas-per-sample 10
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import lede

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external import loaders
from benchmarks.external.cascade_shootout import _answer, _lanes
from benchmarks.external.consolidators import extractive
from benchmarks.external.locomo_chunker_shootout import _dialog
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_RETRIEVAL = ["rrf", "cascade_a", "cascade_b"]
_PACKING = ["raw", "digest", "facts"]


def _digest(chunks: list[str], q: str) -> str:
    if not chunks:
        return ""
    rep = lede.readable_report("\n\n".join(chunks), hints=[q]).to_markdown()
    top5 = "\n\n---\n\n".join(chunks[:5])
    return f"{rep}\n\n## Retrieved Chunks\n\n{top5}"


def _facts(chunks: list[str], q: str) -> str:
    if not chunks:
        return ""
    base = _digest(chunks, q)
    out = extractive.consolidate("\n\n".join(chunks), date_mode="both", max_facts=12)
    lines = "\n".join(f"- {f['support_span']}" for f in out["facts"])
    return f"{base}\n\n## Facts\n\n{lines}"


def _pack(kind: str, chunks: list[str], q: str) -> str:
    if kind == "raw":
        return "\n\n".join(chunks)
    if kind == "digest":
        return _digest(chunks, q)
    return _facts(chunks, q)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-samples", type=int, default=5)
    ap.add_argument("--qas-per-sample", type=int, default=10)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cascade-shootout"))
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

    lanes = [f"{r}+{p}" for r in _RETRIEVAL for p in _PACKING]
    tally = {ln: 0 for ln in lanes}
    n_q = 0
    rows = []
    for s in loaders.load_locomo()[: args.max_samples]:
        sid = s["sample_id"]
        text = _dialog(s["conversation"])
        st = Stele(config=StashConfig(
            backend=BackendConfig(type="postgres", dsn=dsn),
            indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                    sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        ns = f"cpm-{sid}"
        try:
            for h in st.list(namespace=ns, limit=10_000).items:
                st.delete(h.reference)
        except Exception:
            pass
        ref = st.store(text, namespace=ns).reference

        taken = 0
        for qa in s["qa"]:
            if qa.get("category") == 5 or taken >= args.qas_per_sample:
                continue
            q = qa["question"]
            gold = str(qa.get("answer", ""))
            taken += 1
            n_q += 1
            retr = _lanes(st, ref, q)  # {rrf|cascade_a|cascade_b: [chunk_text,...]}
            per_q = {"sid": sid, "question": q, "gold": gold, "lanes": {}}
            line = [f"{sid}:{taken}"]
            for r in _RETRIEVAL:
                for p in _PACKING:
                    ctx = _pack(p, retr[r], q)
                    a = _answer(ans, ctx, q)
                    ok = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    ln = f"{r}+{p}"
                    tally[ln] += ok
                    per_q["lanes"][ln] = {"answer": a, "correct": ok, "ctx_chars": len(ctx)}
                    line.append(f"{ln}={'✓' if ok else '✗'}")
            rows.append(per_q)
            print("  ".join(line), flush=True)
        st.close()

    print(f"\n=== TALLY (n={n_q}, postgres, 3 retrieval x 3 packing) ===")
    print(f"{'lane':18s} {'jscore':>10s}")
    for ln in sorted(lanes, key=lambda x: -tally[x]):
        print(f"{ln:18s} {tally[ln]:>4d}/{n_q}  ({tally[ln]/max(1,n_q):.2f})")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"packing-matrix-{stamp}.json"
    f.write_text(json.dumps({
        "config": "sentence_aware+bge+1000+nbr1 / postgres / k=10 pool=30",
        "n": n_q, "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

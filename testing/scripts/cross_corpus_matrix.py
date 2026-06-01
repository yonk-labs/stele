# ruff: noqa: E501,SIM115  -- benchmark helper.
"""Cross-corpus validation of the promoted defaults (postgres / pgvector).

Runs stele in its NEW out-of-box config (sentence_aware + bge + sync + hybrid)
across three domains that load from the local HF cache:

  locomo            conversational / temporal memory (multi-Q per conversation)
  ragbench-hotpotqa multi-hop factoid RAG
  ragbench-covidqa  biomedical domain QA

Lanes (does the §1-6 story hold cross-domain?):
  keyword     old default: keyword retrieval, raw top-k                (baseline)
  hybrid_raw  new default: hybrid retrieval, raw top-k chunks
  hybrid_facts hybrid retrieval + digest+facts packing
  raw_fetch   full document (accuracy ceiling)

Answerer qwen@193, judge gemma@133 (Mem0 jscore, abstention=wrong) — both local.

Run:  STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele OPENAI_API_KEY=local \
      .venv/bin/python -m benchmarks.external.cross_corpus_matrix --per-corpus 75
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
from benchmarks.external import loaders
from benchmarks.external.cascade_packing_matrix import _facts
from benchmarks.external.cascade_shootout import _answer
from benchmarks.external.locomo_chunker_shootout import _dialog
from stele.core.config import BackendConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_LANES = ["keyword", "hybrid_raw", "hybrid_facts", "raw_fetch"]


def _units(corpus: str, budget: int) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Yield (unit_id, content_text, [(question, gold), ...]) until ~budget Qs."""
    out: list[tuple[str, str, list[tuple[str, str]]]] = []
    n = 0
    if corpus == "locomo":
        for s in loaders.load_locomo():
            qas = [(qa["question"], str(qa.get("answer", "")))
                   for qa in s["qa"] if qa.get("category") != 5][:10]
            if not qas:
                continue
            out.append((s["sample_id"], _dialog(s["conversation"]), qas))
            n += len(qas)
            if n >= budget:
                break
    else:
        subset = corpus.split("-", 1)[1]
        for item in loaders.load_ragbench(subset, limit=budget):
            docs = item.get("documents") or []
            content = "\n\n".join(docs if isinstance(docs, list) else [str(docs)])
            out.append((str(item["id"]), content, [(item["question"], str(item["response"]))]))
            n += 1
            if n >= budget:
                break
    return out


def _pack(lane: str, st: Stele, ref: str, content: str, q: str) -> str:
    if lane == "raw_fetch":
        return content
    mode = "keyword" if lane == "keyword" else "hybrid"
    hits = st.search(ref, q, limit=10, mode=mode)
    chunks = [h.text for h in hits]
    if lane == "hybrid_facts":
        return _facts(chunks, q)
    return "\n\n".join(chunks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=75)
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

    tally: dict[str, dict[str, dict[str, int]]] = {}
    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        tally[corpus] = {ln: {"ok": 0, "n": 0} for ln in _LANES}
        units = _units(corpus, args.per_corpus)
        # one store reused across a corpus; promoted DEFAULT config (no overrides)
        st = Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn)))
        ns = f"xc-{corpus}"
        try:
            for h in st.list(namespace=ns, limit=100_000).items:
                st.delete(h.reference)
        except Exception:
            pass
        done = 0
        for unit_id, content, qas in units:
            ref = st.store(content, namespace=ns).reference
            for q, gold in qas:
                packs = {ln: _pack(ln, st, ref, content, q) for ln in _LANES}
                per = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for ln in _LANES:
                    a = _answer(ans, packs[ln], q)
                    ok = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    tally[corpus][ln]["ok"] += ok
                    tally[corpus][ln]["n"] += 1
                    per["lanes"][ln] = {"answer": a, "correct": ok}
                rows.append(per)
                done += 1
                if done % 10 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        st.close()
        line = " ".join(f"{ln}={tally[corpus][ln]['ok']}/{tally[corpus][ln]['n']}" for ln in _LANES)
        print(f"[{corpus}] {line}", flush=True)

    print("\n=== CROSS-CORPUS TALLY (promoted defaults, postgres) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for ln in _LANES:
            t = tally[corpus][ln]
            acc = t["ok"] / t["n"] if t["n"] else 0.0
            print(f"  {ln:13s} {t['ok']:>3d}/{t['n']:<3d}  ({acc:.2f})")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"cross-corpus-{stamp}.json"
    f.write_text(json.dumps({"config": "promoted-defaults sentence_aware+bge+sync+hybrid / postgres",
                             "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

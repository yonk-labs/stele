# ruff: noqa: E501,SIM115  -- benchmark helper.
"""Retrieval cascade shootout (postgres / pgvector).

Compares hybrid retrieval *architectures* on the 10 lane-gap questions, holding
the substrate constant (sentence_aware + bge-base + 1000-char + neighbor=1):

  rrf        stele's current Reciprocal-Rank-Fusion hybrid (parallel, k=60)
  cascade_a  FTS-first  -> semantic rerank   (narrow by high-signal keywords,
                                              then order survivors by vector rank)
  cascade_b  semantic-first -> keyword rerank (narrow by vector top-N,
                                              then order survivors by keyword rank)

Packing is raw top-k chunks (NO lede) so this isolates *retrieval*, not packing.
Digest / digest+facts layer onto the winning lane in a follow-up.

Metrics per lane: jscore-correct (gemma@133, Mem0 prompt, abstention=wrong) and a
gold-in-context recall proxy (does the gold answer string appear in the packed
context). Answerer qwen@193, judge gemma@133 — both local, per instruction.

Run:  STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele \
      .venv/bin/python -m benchmarks.external.cascade_shootout
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external import loaders
from benchmarks.external.locomo_chunker_shootout import _dialog
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_ROOT = Path("benchmarks/runs/lane-gaps")
_K = 10
_POOL = 30


def _key(h: Any) -> tuple[str, str | None]:
    return (h.artifact_id, h.chunk_id)


def _lanes(st: Stele, ref: str, q: str) -> dict[str, list[str]]:
    """Return {lane: [chunk_text, ...]} top-_K for each retrieval architecture."""
    cs = st._chunk_store
    assert cs is not None
    vec = cs.vector_search(q, limit=10_000, reference=ref)   # full text, vector-ranked
    kw = cs.keyword_search(q, limit=10_000, reference=ref)   # keyword-ranked (snippets)
    full = {_key(h): h.text for h in vec}                    # full chunk text by id
    vrank = {_key(h): i for i, h in enumerate(vec)}
    krank = {_key(h): i for i, h in enumerate(kw)}

    # (a) FTS-first -> semantic rerank: top-POOL keyword keys, ordered by vector rank
    a_keys = sorted((_key(h) for h in kw[:_POOL]), key=lambda k: vrank.get(k, 1 << 30))[:_K]
    # (b) semantic-first -> keyword rerank: top-POOL vector keys, ordered by keyword rank
    b_keys = sorted((_key(h) for h in vec[:_POOL]), key=lambda k: krank.get(k, 1 << 30))[:_K]

    rrf = st.search(ref, q, limit=_K, mode="hybrid")
    return {
        "rrf": [h.text for h in rrf],
        "cascade_a": [full[k] for k in a_keys if k in full],
        "cascade_b": [full[k] for k in b_keys if k in full],
    }


def _answer(ans: OpenAICompatAnswerer, ctx: str, q: str) -> str:
    user = ("Answer using ONLY the memory record. If absent, say "
            "\"I do not have enough information to answer.\"\n\n"
            f"[MEMORY]\n{ctx}\n\n[QUESTION] {q}")
    return str(ans._chat(model=_QWEN, json_mode=False,
                         messages=[{"role": "user", "content": user}])).strip()


def main() -> None:
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

    samples = {s["sample_id"]: s for s in loaders.load_locomo()}
    metas = []
    for folder in sorted(glob.glob(str(_ROOT / "q*"))):
        m = json.loads(next(Path(folder).glob("raw_fetch.json")).read_text())
        metas.append((Path(folder).name, m["sid"], m["question"], str(m["gold"])))

    sid = metas[0][1]
    assert all(s == sid for _, s, _, _ in metas), "expected all questions on one conversation"
    text = _dialog(samples[sid]["conversation"])
    st = Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1),
        retrieval=RetrievalConfig(default_mode="hybrid")))
    ns = "cascade-shootout"
    try:
        for h in st.list(namespace=ns, limit=10_000).items:
            st.delete(h.reference)
    except Exception:
        pass
    ref = st.store(text, namespace=ns).reference

    lane_names = ["rrf", "cascade_a", "cascade_b"]
    tally = {ln: {"correct": 0, "recall": 0} for ln in lane_names}
    rows = []
    for name, _sid, q, gold in metas:
        lanes = _lanes(st, ref, q)
        line = [name]
        per_q = {"q": name, "question": q, "gold": gold, "lanes": {}}
        for ln in lane_names:
            chunks = lanes[ln]
            ctx = "\n\n".join(chunks)
            a = _answer(ans, ctx, q)
            ok = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
            recall = gold.lower() in ctx.lower()
            tally[ln]["correct"] += ok
            tally[ln]["recall"] += recall
            per_q["lanes"][ln] = {"answer": a, "correct": ok, "gold_in_ctx": recall, "n_chunks": len(chunks)}
            line.append(f"{ln}={'✓' if ok else '✗'}{'R' if recall else '·'}")
        rows.append(per_q)
        print("  ".join(line))
    st.close()

    print("\n=== TALLY (n=10, postgres, raw-chunk packing) ===")
    print(f"{'lane':12s} {'jscore':>8s} {'gold_in_ctx':>12s}")
    for ln in lane_names:
        print(f"{ln:12s} {tally[ln]['correct']:>6d}/10 {tally[ln]['recall']:>10d}/10")

    out = _ROOT.parent / "cascade-shootout"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (out / f"shootout-{stamp}.json").write_text(json.dumps(
        {"config": "sentence_aware+bge+1000+nbr1 / postgres / raw-chunks / k=10 pool=30",
         "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {out}/shootout-{stamp}.json")


if __name__ == "__main__":
    main()

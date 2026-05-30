# ruff: noqa: E501,SIM115  -- diagnostic helper.
"""Re-capture the 10 lane-gap questions under the CURRENT config.

Rebuilds each question's conversation index with today's defaults (bge-base
embeddings, bigger chunks) across the current lanes, and writes a fresh
timestamped JSON PER LANE into each existing q*/ folder (old captures kept).

Lanes captured (with the actual chunks handed to the model + answer + verdict):
  raw_fetch            full conversation
  raw_chunks_fixed     top-k fixed_overlap chunks, NO lede
  raw_chunks_sentence  top-k sentence_aware+neighbor chunks, NO lede
  digest_fixed         lede over fixed_overlap chunks
  digest_sentence      lede over sentence_aware chunks

So you can eyeball: does raw_chunks contain the answer that digest's lede dropped?
Answerer qwen@193, judge gemma@133 (local).
"""
from __future__ import annotations

import glob
import json
import os
import time
from pathlib import Path
from typing import Any

import lede

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external import loaders
from benchmarks.external.locomo_chunker_shootout import _dialog
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_ROOT = Path("benchmarks/runs/lane-gaps")


def _digest(hits: list[Any]) -> tuple[str, list[str]]:
    chunks = [h.text for h in hits]
    if not hits:
        return "", []
    rep = lede.readable_report("\n\n".join(chunks), hints=["__q__"]).to_markdown()
    top5 = "\n\n---\n\n".join(chunks[:5])
    return f"{rep}\n\n## Retrieved Chunks\n\n{top5}", [rep, *chunks[:5]]


def _answer(ans: OpenAICompatAnswerer, ctx: str, q: str) -> str:
    user = ("Answer using ONLY the memory record. If absent, say "
            "\"I do not have enough information to answer.\"\n\n"
            f"[MEMORY]\n{ctx}\n\n[QUESTION] {q}")
    return str(ans._chat(model=_QWEN, json_mode=False,
                         messages=[{"role": "user", "content": user}])).strip()


def main() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rj)
    os.environ.get("OPENAI_API_KEY", "")  # judge is local; answerer local
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_GEMMA,
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="http://192.168.1.133:8000/v1", judge_api_key="local")
    judge = OpenAICompatAnswerer(answer_model=_GEMMA, judge_model=_GEMMA,
                                 base_url="http://192.168.1.133:8000/v1", api_key="local")
    samples = {s["sample_id"]: s for s in loaders.load_locomo()}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    for folder in sorted(glob.glob(str(_ROOT / "q*"))):
        d = Path(folder)
        meta = json.loads(next(d.glob("raw_fetch.json")).read_text())
        sid, q, gold = meta["sid"], meta["question"], meta["gold"]
        text = _dialog(samples[sid]["conversation"])
        fo = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/recap-fo-{sid}.db"),
            indexing=IndexingConfig(mode="sync", provider="chunkshop"),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        sa = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/recap-sa-{sid}.db"),
            indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                    sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        fref = fo.store(text, namespace=sid).reference
        sref = sa.store(text, namespace=sid).reference
        foh = fo.search(fref, q, limit=10, mode="hybrid")
        sah = sa.search(sref, q, limit=10, mode="hybrid")
        dfx, dfx_chunks = _digest(foh)
        dse, dse_chunks = _digest(sah)
        lanes = {
            "raw_fetch": (text, [text]),
            "raw_chunks_fixed": ("\n\n".join(h.text for h in foh), [h.text for h in foh]),
            "raw_chunks_sentence": ("\n\n".join(h.text for h in sah), [h.text for h in sah]),
            "digest_fixed": (dfx, dfx_chunks),
            "digest_sentence": (dse, dse_chunks),
        }
        line = [f"{d.name}:"]
        for tag, (ctx, chunks) in lanes.items():
            a = _answer(ans, ctx, q)
            ok = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
            (d / f"{tag}-{stamp}.json").write_text(json.dumps({
                "question": q, "sid": sid, "gold": gold, "lane": tag, "config": "bge-base+bigger-chunks",
                "answer": a, "correct": ok, "n_chunks": len(chunks), "chunks": chunks,
            }, indent=2))
            line.append(f"{tag}={'✓' if ok else '✗'}")
        fo.close()
        sa.close()
        print("  ".join(line))
    print(f"\nwrote *-{stamp}.json per lane into {_ROOT}/q*")


if __name__ == "__main__":
    main()

# ruff: noqa: E501,SIM115  -- benchmark helper.
"""Digest variants: (c) sentence_aware substrate + (b) expanded hints.

Tests whether the two fixes help the digest lane on LoCoMo. Same packing
(lede.readable_report + top chunks); the variables are the chunker substrate
and whether hints are synonym-expanded via lede_spacy.expand_hints.

Lanes:
  raw_fetch            full text (reference ceiling)
  digest_fixed         fixed_overlap substrate, plain hints=[query]   (baseline)
  digest_sentence      sentence_aware+neighbor substrate, plain hints  (c)
  digest_fixed_exp     fixed_overlap substrate, EXPANDED hints         (b)
  digest_sentence_exp  sentence_aware substrate, EXPANDED hints        (b+c)

Answerer qwen@193 (local). Judge gemma@133 (local) — per instruction.
Rows stored for re-judging.
"""
from __future__ import annotations

import argparse
import json
import re
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
_STOP = {"what", "when", "where", "who", "did", "does", "is", "are", "the", "a", "an",
         "to", "of", "in", "on", "for", "her", "his", "their", "would", "be", "likely"}


def _expanded(query: str) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z]+", query) if w.lower() not in _STOP and len(w) > 2]
    try:
        import lede_spacy
        out = lede_spacy.expand_hints(words, kinds=("synonyms",), top_k=3)
        return list(out) if out else (words or [query])
    except Exception:
        return words or [query]


def _digest(hits: list[Any], hints: list[str]) -> str:
    if not hits:
        return ""
    rep = lede.readable_report("\n\n".join(h.text for h in hits), hints=hints)
    top5 = "\n\n---\n\n".join(h.text for h in hits[:5])
    return f"{rep.to_markdown()}\n\n## Retrieved Chunks\n\n{top5}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-samples", type=int, default=5)
    ap.add_argument("--qas-per-sample", type=int, default=20)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/digest-variants"))
    args = ap.parse_args()
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_GEMMA,
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="http://192.168.1.133:8000/v1", judge_api_key="local")
    rows: list[dict[str, Any]] = []
    for s in loaders.load_locomo()[: args.max_samples]:
        sid = s["sample_id"]
        text = _dialog(s["conversation"])
        fo = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/dv-fo-{sid}.db"),
            indexing=IndexingConfig(mode="sync", provider="chunkshop"),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        sa = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/dv-sa-{sid}.db"),
            indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                    sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        fref = fo.store(text, namespace=sid).reference
        sref = sa.store(text, namespace=sid).reference
        taken = 0
        for qa in s["qa"]:
            if qa.get("category") == 5 or taken >= args.qas_per_sample:
                continue
            q = qa["question"]
            gold = str(qa.get("answer", ""))
            taken += 1
            foh = fo.search(fref, q, limit=10, mode="hybrid")
            sah = sa.search(sref, q, limit=10, mode="hybrid")
            ctxs = {
                "raw_fetch": text,
                # raw_chunks: top-k retrieved chunks concatenated, NO lede packing
                "raw_chunks_fixed": "\n\n".join(h.text for h in foh),
                "raw_chunks_sentence": "\n\n".join(h.text for h in sah),
                "digest_fixed": _digest(foh, [q]),
                "digest_sentence": _digest(sah, [q]),
            }
            for tag, ctx in ctxs.items():
                a = _answer(ans, ctx, q)
                rows.append({"sid": sid, "tag": tag, "question": q, "expected": gold,
                             "answer": a, "ctx_chars": len(ctx)})
        fo.close()
        sa.close()
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = args.out / f"variants-{stamp}.json"
    out.write_text(json.dumps({"rows": rows}, indent=2))
    print(f"wrote {out}  rows={len(rows)}")


def _answer(ans: OpenAICompatAnswerer, ctx: str, q: str) -> str:
    user = ("Answer using ONLY the memory record. If absent, say "
            "\"I do not have enough information to answer.\"\n\n"
            f"[MEMORY]\n{ctx}\n\n[QUESTION] {q}")
    return str(ans._chat(model=_QWEN, json_mode=False,
                         messages=[{"role": "user", "content": user}])).strip()


if __name__ == "__main__":
    main()

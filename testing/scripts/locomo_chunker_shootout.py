"""Chunker-shape shootout: is the win compression or enrichment?

Four lanes on LoCoMo, qwen answerer, rows stored for gpt-4o jscore:
  raw_fetch     full artifact text (accuracy ceiling, max tokens)
  digest        fixed_overlap + lede.readable_report(hits, hints=[q]) + top chunks
  consolidation consolidation chunker + extractive consolidator (DISTILLED facts)
  enriching     consolidation chunker + enriching consolidator (VERBATIM turns +
                speaker/date metadata, fact_max_chars raised so nothing truncates)

Hypothesis: enriching >= digest on accuracy (keeps raw words) while staying far
below raw_fetch on tokens — i.e. the value was enrichment, not compression.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import lede

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external import loaders
from stele.core.config import (
    BackendConfig,
    IndexingConfig,
    RetrievalConfig,
    StashConfig,
)
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"


def _dialog(conv: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(conv):
        if not key.startswith("session_") or not isinstance(conv[key], list):
            continue
        dt = conv.get(f"{key}_date_time")
        if isinstance(dt, str) and dt:
            parts.append(f"[Session date: {dt}]")
        for turn in conv[key]:
            if isinstance(turn, dict) and turn.get("text"):
                parts.append(f"[{turn.get('speaker','?')}] {turn['text']}")
    return "\n".join(parts)


def _cons_cfg(path: str, module: str, fact_max_chars: int, max_facts: int) -> StashConfig:
    # consolidation ranks + keeps top-N informative facts (60 is plenty).
    # enriching KEEPS EVERY turn (high cap) and lets retrieval pick top-k — its
    # whole point is no compression, so it must not drop turns in doc order.
    return StashConfig(
        backend=BackendConfig(type="sqlite", path=path),
        indexing=IndexingConfig(
            mode="sync", provider="chunkshop", chunker="consolidation",
            consolidator_module=module,
            consolidator_kwargs={"max_facts": max_facts, "date_mode": "both"},
            fact_max_chars=fact_max_chars,
        ),
        retrieval=RetrievalConfig(default_mode="hybrid"),
    )


def _pack(hits: list[Any]) -> str:
    summ = [h.text for h in hits if (h.metadata or {}).get("kind") == "episode"]
    facts = [h.text for h in hits if (h.metadata or {}).get("kind") != "episode"]
    out = []
    if summ:
        out.append("[SUMMARY]\n" + "\n".join(summ))
    if facts:
        out.append("[FACTS]\n" + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-samples", type=int, default=5)
    ap.add_argument("--qas-per-sample", type=int, default=20)
    ap.add_argument("--answer-base-url", default="http://192.168.1.193:8000/v1")
    ap.add_argument("--answer-model", default=_QWEN)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/chunker-shootout"))
    args = ap.parse_args()

    key = os.environ["OPENAI_API_KEY"]
    answerer = OpenAICompatAnswerer(
        answer_model=args.answer_model, judge_model="gpt-4o",
        base_url=args.answer_base_url, api_key="local",
        judge_base_url="https://api.openai.com/v1", judge_api_key=key,
    )
    rows: list[dict[str, Any]] = []
    for s in loaders.load_locomo()[: args.max_samples]:
        sid = s["sample_id"]
        text = _dialog(s["conversation"])
        fo = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/shoot-fo-{sid}.db"),
            indexing=IndexingConfig(mode="sync", provider="chunkshop"),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        cons = Stele(config=_cons_cfg(f"/tmp/shoot-co-{sid}.db",
                     "benchmarks.external.consolidators.extractive", 200, 60))
        enr = Stele(config=_cons_cfg(f"/tmp/shoot-en-{sid}.db",
                    "benchmarks.external.consolidators.enriching", 1000, 1000))
        fo_ref = fo.store(text, namespace=sid).reference
        cons.store(text, namespace=sid)
        enr.store(text, namespace=sid)

        taken = 0
        for qa in s["qa"]:
            if qa.get("category") == 5 or taken >= args.qas_per_sample:
                continue
            q = qa["question"]
            expected = str(qa.get("answer", ""))
            taken += 1
            # build each lane's context
            ctxs: dict[str, str] = {}
            ctxs["raw_fetch"] = text
            dh = fo.search(fo_ref, q, limit=10, mode="hybrid")
            if dh:
                rep = lede.readable_report("\n\n".join(h.text for h in dh), hints=[q])
                top5 = "\n\n---\n\n".join(h.text for h in dh[:5])
                ctxs["digest"] = f"{rep.to_markdown()}\n\n## Retrieved Chunks\n\n{top5}"
            else:
                ctxs["digest"] = ""
            ctxs["consolidation"] = _pack(cons.query(sid, q, limit=15, mode="hybrid"))
            # enriching: turn-level chunks, deeper retrieval (the substrate raw).
            ctxs["enriching"] = _pack(enr.query(sid, q, limit=30, mode="hybrid"))
            # digest_enriched: digest PACKING over the enriched substrate —
            # lede-distill the retrieved enriched turn-chunks + keep the top ones.
            eh = enr.query(sid, q, limit=15, mode="hybrid")
            if eh:
                erep = lede.readable_report("\n\n".join(h.text for h in eh), hints=[q])
                etop = "\n\n".join(h.text for h in eh[:8])
                ctxs["digest_enriched"] = f"{erep.to_markdown()}\n\n## Facts\n\n{etop}"
            else:
                ctxs["digest_enriched"] = ""
            for tag, ctx in ctxs.items():
                ans = _answer(answerer, args.answer_model, ctx, q)
                rows.append({"sid": sid, "tag": tag, "question": q,
                             "expected": expected, "answer": ans,
                             "ctx_chars": len(ctx)})
        for st in (fo, cons, enr):
            st.close()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = args.out / f"shootout-{stamp}.json"
    out.write_text(json.dumps({"rows": rows}, indent=2))
    print(f"wrote {out}  rows={len(rows)}")


def _answer(answerer: Any, model: str, context: str, question: str) -> str:
    user = (
        "Answer using ONLY the memory record. If absent, say "
        "\"I do not have enough information to answer.\"\n\n"
        f"[MEMORY]\n{context}\n\n[QUESTION] {question}"
    )
    return str(answerer._chat(  # noqa: SLF001
        model=model, json_mode=False,
        messages=[{"role": "user", "content": user}],
    )).strip()


if __name__ == "__main__":
    main()

"""Does entity filtering help on LoCoMo? (the testable filter subset)

~99% of LoCoMo questions name a participant, so they're entity-filterable via
metadata.subject on consolidation facts. This measures whether that filter
actually improves answer accuracy, or whether it's redundant with ranking
(entity NAMES are lexical tokens vector/keyword already surface — unlike dates).

For each conversation: store it, index with the LLM consolidator (subject =
real fact subject), then for each participant-naming question compare:
  baseline : query(consolidation)                 — rank only
  entity   : query(consolidation, filters=subject) — filter-then-rank

qwen answerer (local), gpt-4o judge + jscore. Stores rows for re-judging.

NOTE the known limitation this does NOT cover: temporal per-fact filtering.
The consolidation chunker emits date info into the fact's support-span TEXT
(date_mode), not as a filterable metadata field, and chunkshop's fact schema
doesn't propagate arbitrary keys — so metadata date-range filtering on facts
needs a consolidator/chunkshop enhancement (emit resolved date as fact
metadata). Documented as a follow-up; only entity filtering is wired today.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-samples", type=int, default=5)
    ap.add_argument("--qas-per-sample", type=int, default=20)
    ap.add_argument("--answer-base-url", default="http://192.168.1.193:8000/v1")
    ap.add_argument("--answer-model", default=_QWEN)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/locomo-entity"))
    args = ap.parse_args()

    key = os.environ["OPENAI_API_KEY"]
    answerer = OpenAICompatAnswerer(
        answer_model=args.answer_model, judge_model="gpt-4o",
        base_url=args.answer_base_url, api_key="local",
        judge_base_url="https://api.openai.com/v1", judge_api_key=key,
    )
    rows: list[dict[str, Any]] = []
    samples = loaders.load_locomo()[: args.max_samples]
    for s in samples:
        sid = s["sample_id"]
        speakers = [s["conversation"].get("speaker_a"), s["conversation"].get("speaker_b")]
        speakers = [sp for sp in speakers if sp]
        stash = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/locent-{sid}.db"),
            indexing=IndexingConfig(
                mode="sync", provider="chunkshop", chunker="consolidation",
                consolidator_module="benchmarks.external.consolidators.llm",
                consolidator_kwargs={
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini", "summary_words": 120, "max_facts": 30,
                },
            ),
            retrieval=RetrievalConfig(default_mode="hybrid"),
        ))
        res = stash.store(_dialog(s["conversation"]), namespace=sid)
        ref = res.reference
        taken = 0
        for qa in s["qa"]:
            if qa.get("category") == 5 or taken >= args.qas_per_sample:
                continue
            q = qa["question"]
            person = next((sp for sp in speakers if sp in q), None)
            if person is None:
                continue
            taken += 1
            expected = str(qa.get("answer", ""))

            def ctx(hits: list[Any]) -> str:
                return "\n".join(h.text for h in hits)

            base_hits = stash.search(ref, q, limit=15, mode="hybrid")
            ent_hits = stash.query(sid, q, limit=15, mode="hybrid",
                                   filters={"metadata.subject": person})
            for tag, hits in (("baseline", base_hits), ("entity", ent_hits)):
                ans, _pt = _answer(answerer, args.answer_model, ctx(hits), q)
                rows.append({"sid": sid, "tag": tag, "person": person, "question": q,
                             "expected": expected, "answer": ans,
                             "n_hits": len(hits)})
        stash.close()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = args.out / f"entity-{stamp}.json"
    out.write_text(json.dumps({"rows": rows}, indent=2))
    print(f"wrote {out}  rows={len(rows)}")


def _answer(answerer: Any, model: str, context: str, question: str) -> tuple[str, int]:
    user = (
        "Answer using ONLY the memory record. If absent, say "
        "\"I do not have enough information to answer.\"\n\n"
        f"[MEMORY]\n{context}\n\n[QUESTION] {question}"
    )
    content = answerer._chat(  # noqa: SLF001
        model=model, json_mode=False,
        messages=[{"role": "user", "content": user}],
    )
    return content.strip(), 0


if __name__ == "__main__":
    main()

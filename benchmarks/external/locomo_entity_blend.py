"""Entity filtering done right: speaker-coref subjects + blended retrieval.

The first cut (locomo_entity_filter.py) failed because it used the LLM
consolidator (verbatim "I went..." spans, unreliable LLM subjects) AND hard
exclusion. Diagnosis: ~all answer-bearing LoCoMo turns are first-person
self-reference ("[Caroline] I went..."), so the speaker tag IS the coref key.

This redo:
- uses the EXTRACTIVE consolidator: subject = speaker (resolves "I" -> Caroline)
  and every span is prefixed "[Caroline] ..." (entity name in the text, so
  ranking can find it too).
- compares three arms:
    base  : no filter (ranking only)
    hard  : filters={metadata.subject: person}  (exclusion)
    blend : filtered facts FIRST, then unfiltered fills to k (boost, not drop)
- qwen answerer (local), rows stored for gpt-4o jscore.
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
_GENERIC = {"i", "we", "you", "they", "he", "she", "it", "?", ""}


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


def _blend(filtered: list[Any], unfiltered: list[Any], k: int) -> list[Any]:
    """Filtered hits first (boosted), then unfiltered fills to k. Dedup by chunk_id."""
    seen: set[str] = set()
    out: list[Any] = []
    for h in [*filtered, *unfiltered]:
        cid = h.chunk_id or h.text
        if cid in seen:
            continue
        seen.add(cid)
        out.append(h)
        if len(out) >= k:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-samples", type=int, default=5)
    ap.add_argument("--qas-per-sample", type=int, default=20)
    ap.add_argument("--answer-base-url", default="http://192.168.1.193:8000/v1")
    ap.add_argument("--answer-model", default=_QWEN)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/locomo-entity-blend"))
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
        speakers = [sp for sp in (s["conversation"].get("speaker_a"),
                                  s["conversation"].get("speaker_b")) if sp]
        stash = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/locblend-{sid}.db"),
            indexing=IndexingConfig(
                mode="sync", provider="chunkshop", chunker="consolidation",
                consolidator_module="benchmarks.external.consolidators.extractive",
                consolidator_kwargs={"summary_words": 120, "max_facts": 30,
                                     "date_mode": "both"},
            ),
            retrieval=RetrievalConfig(default_mode="hybrid"),
        ))
        res = stash.store(_dialog(s["conversation"]), namespace=sid)
        taken = 0
        for qa in s["qa"]:
            if qa.get("category") == 5 or taken >= args.qas_per_sample:
                continue
            q = qa["question"]
            person = next((sp for sp in speakers if sp in q), None)
            if person is None or person.lower() in _GENERIC:
                continue
            taken += 1
            expected = str(qa.get("answer", ""))
            unfiltered = stash.query(sid, q, limit=15, mode="hybrid")
            filtered = stash.query(sid, q, limit=15, mode="hybrid",
                                   filters={"metadata.subject": person})
            arms = {
                "base": unfiltered,
                "hard": filtered if filtered else unfiltered,
                "blend": _blend(filtered, unfiltered, 15),
            }
            for tag, hits in arms.items():
                ctx = "\n".join(h.text for h in hits)
                ans = _answer(answerer, args.answer_model, ctx, q)
                rows.append({"sid": sid, "tag": tag, "person": person, "question": q,
                             "expected": expected, "answer": ans, "n_hits": len(hits),
                             "n_filtered": len(filtered)})
        stash.close()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = args.out / f"blend-{stamp}.json"
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

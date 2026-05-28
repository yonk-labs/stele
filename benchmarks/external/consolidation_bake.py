"""Self-contained ConsolidationChunker bake-off (n=30 LoCoMo).

Runs chunkshop's actual ConsolidationChunker.chunk() pipeline per LoCoMo
conversation, builds context from the resulting episode + fact chunks,
answers each QA with an OpenAI-compatible model, and persists
question/expected/answer/context per row so we can re-judge with jscore
(Mem0's prompt) for apples-to-apples comparison with the existing
same-ruler stele-vs-Mem0 table.

Two modes, selectable via --consolidator:
- extractive: deterministic, no API cost (benchmarks.external.consolidators.extractive)
- llm: real distillation via OPENAI_API_KEY (benchmarks.external.consolidators.llm)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from chunkshop.chunkers import load_chunker
from chunkshop.config import (
    CallableConsolidator,
    ConsolidationChunker,
    FixedOverlapChunker,
)
from chunkshop.sources.base import Document

from benchmarks.external import loaders


def _build_dialog_text(conv: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, val in conv.items():
        if key.startswith("session_") and key.endswith("_date_time"):
            parts.append(f"[{val}]")
        elif key.startswith("session_") and isinstance(val, list):
            for t in val:
                parts.append(f"[{t.get('speaker', '?')}] {t.get('text', '')}")
    return "\n".join(parts)


def _build_context(chunks: list[Any]) -> tuple[str, int, int]:
    summary = ""
    facts: list[str] = []
    for c in chunks:
        kind = (c.metadata or {}).get("kind")
        if kind == "episode":
            summary = c.embedded_content or c.original_content or ""
        elif kind == "fact":
            m = c.metadata or {}
            spo = f"{m.get('subject','?')} | {m.get('predicate','?')} | {m.get('object','?')}"
            span = m.get("support_span") or c.original_content or ""
            facts.append(f"- {spo} :: {span}")
    body = f"[SUMMARY]\n{summary}\n\n[FACTS]\n" + ("\n".join(facts) if facts else "(none)")
    return body, len(summary), len(facts)


def _answer(client: Any, model: str, context: str, question: str) -> tuple[str, int]:
    user = (
        f"You are answering questions about a conversation. Use ONLY the "
        f"memory record below. If the answer isn't in the record, say "
        f"\"I do not have enough information to answer.\"\n\n"
        f"[MEMORY RECORD]\n{context}\n\n[QUESTION] {question}"
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user}],
    }
    if not model.startswith("gpt-5"):
        kwargs["temperature"] = 0.0
    resp = client.chat.completions.create(**kwargs)
    ans = resp.choices[0].message.content or ""
    pt = int(getattr(resp.usage, "prompt_tokens", 0) or 0)
    return ans.strip(), pt


def _judge(client: Any, judge_model: str, *, question: str, expected: str,
           answer: str, context: str) -> bool:
    system = (
        "You evaluate whether the candidate answer is correct against the gold "
        "answer for a memory recall task. Return JSON {match: bool, confidence: 0..1}. "
        "Mark TRUE only if the candidate clearly contains the gold answer (paraphrase OK). "
        "Refusals ('I do not have enough information') => FALSE. Use ONLY the gold; do not "
        "judge the world."
    )
    user = (
        f"Question:\n{question}\n\nGold:\n{expected or '(none)'}\n\n"
        f"Candidate:\n{answer}\n\nContext the candidate had:\n{context}"
    )
    kwargs: dict[str, Any] = {
        "model": judge_model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    if not judge_model.startswith("gpt-5"):
        kwargs["temperature"] = 0.0
    resp = client.chat.completions.create(**kwargs)
    raw = resp.choices[0].message.content or "{}"
    try:
        return bool(json.loads(raw).get("match", False))
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consolidator", required=True, choices=["extractive", "llm"])
    ap.add_argument("--max-samples", type=int, default=3, help="LoCoMo conversations")
    ap.add_argument("--qas-per-sample", type=int, default=10)
    ap.add_argument("--answer-model", default="gpt-4o-mini")
    ap.add_argument("--judge-model", default="gpt-4o")
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--consolidator-model", default="gpt-4o-mini",
                    help="Model used by the LLM consolidator (ignored for extractive)")
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/consolidation"))
    args = ap.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY not set")
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=args.base_url)

    mod = (
        "benchmarks.external.consolidators.extractive"
        if args.consolidator == "extractive"
        else "benchmarks.external.consolidators.llm"
    )
    cons_kwargs: dict[str, Any] = {"summary_words": 120, "max_facts": 12}
    if args.consolidator == "llm":
        cons_kwargs.update({"base_url": args.base_url, "model": args.consolidator_model})

    cfg = ConsolidationChunker(
        type="consolidation",
        base=FixedOverlapChunker(type="fixed_overlap", window_words=400, step_words=400),
        consolidator=CallableConsolidator(
            mode="callable", module=mod, function="consolidate", kwargs=cons_kwargs,
        ),
        fact_max_chars=200,
    )
    chunker = load_chunker(cfg)

    samples = loaders.load_locomo()[: args.max_samples]
    print(f"loaded {len(samples)} LoCoMo conversations")

    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    ok = 0
    total_consolidate = 0.0
    total_prompt_tokens = 0

    for s in samples:
        sid = s["sample_id"]
        dialog = _build_dialog_text(s["conversation"])
        t0 = time.perf_counter()
        chunks = chunker.chunk(Document(id=sid, content=dialog, metadata={}))
        total_consolidate += time.perf_counter() - t0
        context, sum_chars, n_facts = _build_context(chunks)
        ctx_chars = len(context)
        print(f"  {sid}: {len(chunks)} chunks ({n_facts} facts), "
              f"summary={sum_chars}ch, context={ctx_chars}ch")
        for i, qa in enumerate(s["qa"][: args.qas_per_sample]):
            if qa.get("category") == 5:
                continue  # skip adversarial like the rest of the harness does
            q = qa["question"]
            expected = str(qa.get("answer", ""))
            try:
                ans, pt = _answer(client, args.answer_model, context, q)
                total_prompt_tokens += pt
                correct = _judge(client, args.judge_model, question=q,
                                 expected=expected, answer=ans, context=context)
            except Exception as e:
                ans = ""
                pt = 0
                correct = False
                print(f"  ERR {sid}:{i}: {e}")
            ok += int(correct)
            rows.append({
                "sample_id": sid, "q_idx": i, "question": q, "expected": expected,
                "answer": ans, "correct": correct, "context": context,
                "prompt_tokens": pt, "context_chars": ctx_chars,
                "n_facts": n_facts,
            })

    n = len(rows)
    acc = ok / n if n else 0.0
    summary = {
        "system": f"chunkshop_consolidation_{args.consolidator}",
        "benchmark": "locomo",
        "n": n,
        "n_convs": len(samples),
        "answer_model": args.answer_model,
        "judge_model": args.judge_model,
        "consolidator_model": args.consolidator_model if args.consolidator == "llm" else None,
        "accuracy": round(acc, 4),
        "mean_prompt_tokens": round(total_prompt_tokens / n, 1) if n else 0.0,
        "consolidate_seconds": round(total_consolidate, 2),
        "results": rows,
    }
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = args.out / f"consolidation-{args.consolidator}-{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out_path}")
    print(f"n={n}  acc={acc:.3f}  mean_prompt_tokens={summary['mean_prompt_tokens']}"
          f"  consolidate_seconds={summary['consolidate_seconds']}")


if __name__ == "__main__":
    main()

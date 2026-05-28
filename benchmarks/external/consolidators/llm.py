# ruff: noqa: E501  -- the consolidator prompt has long lines on purpose.
"""LLM consolidator for chunkshop's ConsolidationChunker.

Contract (chunkshop CallableConsolidator):
    consolidate(text, **kwargs) -> {"summary": str, "facts": [{...}]}

Real distillation: prompts an OpenAI-compatible model for {summary, facts}
as JSON. Mirrors how Mem0's ingest distills a conversation into atomic
memories before storage. API key read from OPENAI_API_KEY env (not from
kwargs — keeps secrets out of any persisted config).
"""
from __future__ import annotations

import json
import os
from typing import Any

_SYSTEM = (
    "You distill a conversation into a compact memory record. Return JSON only."
)
_USER_TEMPLATE = """Below is a conversation (possibly multi-session). Produce a JSON object with:
- summary: at most {summary_words} words covering the load-bearing facts, decisions, dates, and entities.
- facts: a list of up to {max_facts} atomic facts as {{"subject": str, "predicate": str, "object": str, "support_span": str (the exact phrase from the conversation supporting the fact, <= 180 chars), "confidence": float in [0,1]}}.

Focus on durable knowledge a reader would need to answer questions later: who, did what, when, with whom, why. Skip pleasantries.

Conversation:
{text}

Return only the JSON object, no commentary."""


def consolidate(
    text: str,
    *,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    summary_words: int = 120,
    max_facts: int = 12,
    text_char_budget: int = 60000,
    **_: Any,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("llm consolidator: OPENAI_API_KEY env var not set")
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    user_msg = _USER_TEMPLATE.format(
        summary_words=summary_words, max_facts=max_facts,
        text=text[:text_char_budget],
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "response_format": {"type": "json_object"},
    }
    if not model.startswith("gpt-5"):
        kwargs["temperature"] = 0.0
    resp = client.chat.completions.create(**kwargs)
    raw = json.loads(resp.choices[0].message.content or "{}")
    facts_out: list[dict[str, Any]] = []
    for f in (raw.get("facts") or [])[:max_facts]:
        facts_out.append({
            "subject": str(f.get("subject") or ""),
            "predicate": str(f.get("predicate") or ""),
            "object": str(f.get("object") or ""),
            "support_span": (str(f.get("support_span") or ""))[:180],
            "confidence": float(f.get("confidence") or 0.5),
        })
    return {
        "summary": str(raw.get("summary") or "").strip(),
        "facts": facts_out,
    }

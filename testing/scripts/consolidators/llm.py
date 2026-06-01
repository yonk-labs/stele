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
_USER_TEMPLATE = """Below is a conversation (possibly multi-session). Distil it into a JSON memory record a future reader will query for specific facts.

Produce a JSON object with:
- summary: at most {summary_words} words. Preserve EVERY date, time, place name, person name, number, and quantity VERBATIM as written (do not paraphrase "last week" — keep both the relative and any absolute date present). Cover who did what, when, where, with whom, and why.
- facts: a list of up to {max_facts} atomic facts. Each is {{"subject": str, "predicate": str, "object": str, "support_span": str, "confidence": float in [0,1]}}. The support_span is the EXACT phrase from the conversation supporting the fact (<= 180 chars), copied verbatim including any date/number/name. Emit one fact per distinct (who, did-what, when/where) — prefer MORE granular facts over fewer broad ones. Every date, event, preference, relationship, decision, and named entity mentioned should appear in at least one fact's support_span.

Rules:
- Never invent or round dates/numbers; copy them exactly.
- A question like "When did X happen?" must be answerable from a support_span — so always keep the date attached to its event in the same span.
- Skip pleasantries and filler.

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

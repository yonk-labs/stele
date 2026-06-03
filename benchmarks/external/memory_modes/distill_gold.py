# ruff: noqa: E501 -- gold fixture.
"""Frozen GOLD = this session's hand-sorted distillation, the target the
distill_* functions must reproduce. Snapshot of the FACTS / PRECEDENTS /
GUARDRAILS fixtures in validate_on_yonk_tools.py (real ~/yonk-tools data),
inlined here so the gold imports no LLM-client deps."""
from __future__ import annotations

GOLD: dict[str, list[dict[str, str]]] = {
    "facts": [
        {"id": "pg-raggraph", "text": "GraphRAG on plain PostgreSQL, no extra services"},
        {"id": "lede", "text": "sub-millisecond extractive summarization, stdlib core"},
        {"id": "llm-judge", "text": "judges RAG/LLM benchmark runs across local/OpenAI/cloud providers"},
        {"id": "pg-lexicon", "text": "Postgres-backed metadata & semantic intelligence; crawls schemas, profiles columns"},
        {"id": "pg-synapse", "text": "Postgres-native agent-loop runtime in Rust"},
        {"id": "pocket_grader", "text": "local LLM-assisted test grading"},
        {"id": "chunkshop", "text": "small standalone embeddable text ingestion tool"},
        {"id": "yonk-robo-codemonkey", "text": "local-first MCP server indexing code+docs into Postgres for hybrid retrieval"},
        {"id": "pg-agent", "text": "PostgreSQL extension making AI agents a database-native primitive"},
        {"id": "pgrx", "text": "framework for building Postgres extensions in Rust"},
        {"id": "skimr-neural", "text": "CPU-only neural abstractive summarization companion"},
        {"id": "yonk-taskstash", "text": "off-prompt memory keeping large/sensitive data out of the context window"},
    ],
    "precedents": [
        {"id": "b8dd415", "query": "had a PyPI upload rejected and fixed a packaging dependency"},
        {"id": "4ce30a7", "query": "retracted a benchmark hypothesis after new data"},
        {"id": "012669d", "query": "scaled an A/B retrieval benchmark on a large multi-hop dataset"},
        {"id": "f555d1a", "query": "renamed a project as part of a release"},
        {"id": "7789191", "query": "built a per-student report generator"},
        {"id": "5b60282", "query": "added error-feedback retry to a text-to-SQL pipeline"},
        {"id": "660a0d7", "query": "cut a plugin to ship a smaller single-plugin release"},
        {"id": "cd67538", "query": "excluded a crate from the clippy workspace in CI"},
        {"id": "bbc8432", "query": "built a context-package CLI with golden fixtures"},
        {"id": "e7a1bd2", "query": "corrected a wrong claim about threads being free"},
    ],
    "rules": [
        {"dont": "use gpt-4o", "do_instead": "use gpt-5-mini", "domain": "config", "in_family": "true"},
        {"dont": "use a single connection", "do_instead": "use a connection pool", "domain": "python", "in_family": "true"},
        {"dont": "edit the vendored llama.cpp test directory", "do_instead": "update the vendored copy deliberately", "domain": "path", "in_family": "true"},
    ],
    "skills": [
        {"id": "async-pools", "text": "all database operations are async, use connection pools"},
    ],
    "best_practices": [
        {"id": "determinism", "text": "prefer a deterministic check over an LLM judge"},
    ],
    "state": [
        {"id": "headroom-hypothesis", "gold": "abandoned"},
        {"id": "pg-lexicon-phase-f", "gold": "done"},
    ],
}


def score_view(mode: str, predicted_ids: list[str]) -> dict[str, float]:
    """Precision / recall / hit@1 of predicted ids against the gold for ``mode``.

    For ``rules``, the gold id is the ``dont`` string.
    """
    gold_items = GOLD[mode]
    gold_ids = {g.get("id") or g.get("dont") or "" for g in gold_items}
    pred = list(predicted_ids)
    pred_set = set(pred)
    tp = len(gold_ids & pred_set)
    recall = tp / len(gold_ids) if gold_ids else 0.0
    precision = tp / len(pred_set) if pred_set else 0.0
    hit_at_1 = 1.0 if pred and pred[0] in gold_ids else 0.0
    return {"recall": recall, "precision": precision, "hit_at_1": hit_at_1}

"""LLM-judged + timed lane over the third-party benchmark datasets.

Bridges the retrieval-recall harness (this package) with the answer +
judge model used by `benchmarks.answer_workflow`. Same OpenAI-compatible
endpoint, same JudgeVerdict schema. Per query records:

  - ingest_ms, recall_ms, answer_ms, judge_ms (wall-clock)
  - prompt_tokens, completion_tokens, total_tokens (estimated)
  - context_chars, recall_hits
  - judged.correct, judged.sufficient, judged.confidence
  - profile name + per-benchmark notes

Output: benchmarks/runs/<date>/judge-lane-<profile>/{Report.{md,json}}.

Honest scope: small N (default 15/benchmark) because the local Qwen3
endpoint runs ~2-5s per LLM call. Headline accuracy is comparable to
vendor LongMemEval / LoCoMo headlines (LLM-as-judge, same metric class).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external import harness, loaders
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round((p / 100) * (len(s) - 1)))
    return s[k]


def _estimate_tokens(text: str) -> int:
    # Same heuristic as answer_workflow: ~4 chars / token.
    return max(1, len(text) // 4)


def _build_context(rr: Any, max_chars: int = 6000) -> tuple[str, int]:
    parts = [str(rr.context)]
    parts.extend(str(c.snippet) for c in rr.citations)
    joined = "\n---\n".join(p for p in parts if p)
    return joined[:max_chars], len(rr.citations)


def _locomo_items(max_q: int) -> Iterator[dict[str, Any]]:
    n = 0
    for sample in loaders.load_locomo()[:5]:
        sid = sample["sample_id"]
        for qa in sample["qa"]:
            if n >= max_q:
                return
            if qa.get("category") == 5:  # abstention questions skipped here
                continue
            yield {
                "benchmark": "locomo",
                "sample_id": sid,
                "sample_obj": sample,
                "question": qa["question"],
                "expected": str(qa.get("answer", "")),
            }
            n += 1


def _mhr_items(max_q: int) -> Iterator[dict[str, Any]]:
    queries, corpus = loaders.load_multihoprag()
    n = 0
    for q in queries:
        if n >= max_q:
            return
        if q.get("question_type") == "null_query":
            continue
        yield {
            "benchmark": "mhr",
            "corpus": corpus,
            "question": q["query"],
            "expected": str(q.get("answer", "")),
        }
        n += 1


def _lme_items(max_q: int) -> Iterator[dict[str, Any]]:
    n = 0
    for rec in loaders.iter_longmemeval_s(max_q):
        if n >= max_q:
            return
        if str(rec.get("question_id", "")).endswith("_abs"):
            continue
        yield {
            "benchmark": "lme",
            "haystack": rec.get("haystack_sessions", []),
            "question": rec["question"],
            "expected": str(rec.get("answer", "")),
        }
        n += 1


def _longbench_items(max_per_task: int) -> Iterator[dict[str, Any]]:
    for task in ("hotpotqa", "2wikimqa", "musique", "multifieldqa_en"):
        for rec in loaders.iter_longbench(task, limit=max_per_task):
            yield {
                "benchmark": f"longbench:{task}",
                "context_raw": rec.get("context", ""),
                "question": rec["input"],
                "expected": str((rec.get("answers") or [""])[0]),
            }


def _ragbench_items(max_per_subset: int) -> Iterator[dict[str, Any]]:
    for subset in ("hotpotqa", "msmarco", "covidqa", "pubmedqa", "techqa", "hagrid"):
        for rec in loaders.load_ragbench(subset, split="test", limit=max_per_subset):
            yield {
                "benchmark": f"ragbench:{subset}",
                "documents": rec.get("documents") or [],
                "question": str(rec.get("question", "")),
                "expected": str(rec.get("response", "") or ""),
            }


def _ingest_locomo(s: Stele, scope: MemoryScope, item: dict[str, Any],
                   use_extract: bool) -> None:
    conv = item["sample_obj"]["conversation"]
    if use_extract:
        for key, val in conv.items():
            if not key.startswith("session_") or not isinstance(val, list):
                continue
            msgs = [
                {"role": t.get("speaker", "user"), "content": t.get("text", "")}
                for t in val if t.get("text")
            ]
            if msgs:
                s.extract.from_messages(messages=msgs, scope=scope)
    else:
        for key, val in conv.items():
            if not key.startswith("session_") or not isinstance(val, list):
                continue
            for turn in val:
                s.memory.add(
                    text=f"[{turn.get('speaker','?')}] {turn.get('text','')}",
                    kind="fact",
                    source_refs=[f"stele://locomo/{item['sample_id']}/"
                                 f"{turn.get('dia_id', 'x')}"],
                    scope=scope,
                )


def _ingest_mhr(s: Stele, scope: MemoryScope, item: dict[str, Any]) -> None:
    for i, doc in enumerate(item["corpus"]):
        body = (doc.get("title", "") + ". " + doc.get("body", ""))[:4000]
        s.memory.add(text=body, kind="fact",
                     source_refs=[f"stele://mhr/doc-{i}"], scope=scope)


def _ingest_lme(s: Stele, scope: MemoryScope, item: dict[str, Any]) -> None:
    for sess in item["haystack"]:
        for turn in sess:
            if not isinstance(turn, dict):
                continue
            s.memory.add(
                text=f"[{turn.get('role','?')}] {turn.get('content','')}"[:1500],
                kind="fact", source_refs=["stele://lme/turn"], scope=scope,
            )


def _ingest_longbench(s: Stele, scope: MemoryScope, item: dict[str, Any]) -> None:
    passages = harness._split_passages(item["context_raw"])
    for j, p in enumerate(passages):
        s.memory.add(text=p[:2000], kind="fact",
                     source_refs=[f"stele://lb/p{j}"], scope=scope)


def _ingest_ragbench(s: Stele, scope: MemoryScope, item: dict[str, Any]) -> None:
    for j, d in enumerate(item["documents"]):
        s.memory.add(text=str(d)[:2000], kind="fact",
                     source_refs=[f"stele://rb/d{j}"], scope=scope)


def run_judge_lane(
    *,
    profile: str,
    answerer: OpenAICompatAnswerer,
    max_locomo: int = 15,
    max_mhr: int = 15,
    max_lme: int = 15,
    max_longbench_per_task: int = 5,
    max_ragbench_per_subset: int = 5,
    k: int | None = None,
) -> dict[str, Any]:
    spec = harness.PROFILES[profile]
    cfg = spec["config"]
    k_eff = k if k is not None else spec["k"]
    use_extract = bool(spec.get("use_stele_extract"))
    if use_extract:
        cfg = dict(cfg)
        ext = dict(cfg.get("extraction") or {})
        ext.setdefault(
            "retain_message_text",
            bool(spec.get("retain_message_text", True)),
        )
        cfg["extraction"] = ext

    locomo_isolated = []  # locomo wants per-sample isolation
    seen_sids: set[str] = set()
    for item in _locomo_items(max_locomo):
        if item["sample_id"] not in seen_sids:
            locomo_isolated.append(item)
            seen_sids.add(item["sample_id"])
    locomo_items = list(_locomo_items(max_locomo))

    mhr_items_list = list(_mhr_items(max_mhr))
    lme_items_list = list(_lme_items(max_lme))
    longbench_items_list = list(_longbench_items(max_longbench_per_task))
    ragbench_items_list = list(_ragbench_items(max_ragbench_per_subset))

    rows: list[dict[str, Any]] = []
    strategy = spec.get("strategy")

    def _safe_ns(raw: str) -> str:
        """pg-raggraph allows [A-Za-z0-9._-] only, max 64 chars."""
        sanitized = "".join(
            c if c.isalnum() or c in "._-" else "-" for c in raw
        )
        return sanitized[:64]

    def _fresh(namespace: str) -> tuple[Stele, str]:
        """Build a Stele with an isolated namespace (postgres+graph needs
        graph.namespace too) and best-effort-purge prior state. Returns
        (Stele, sanitized_namespace) so the caller's MemoryScope uses
        the same sanitized string the graph layer does."""
        ns = _safe_ns(namespace)
        c = dict(cfg)
        if "graph" in c:
            graph = dict(c["graph"])
            graph["namespace"] = ns
            c["graph"] = graph
        st = Stele.from_config(c)
        with contextlib.suppress(Exception):
            st.purge_namespace(ns)
        return st, ns

    # -- LoCoMo (per-sample isolated Stele instances)
    for sid in sorted({i["sample_id"] for i in locomo_items}):
        sample_qs = [i for i in locomo_items if i["sample_id"] == sid]
        s, ns = _fresh(f"locomo_{sid}")
        scope = MemoryScope(namespace=ns)
        t0 = time.perf_counter()
        _ingest_locomo(s, scope, sample_qs[0], use_extract=use_extract)
        ingest_ms = (time.perf_counter() - t0) * 1000
        for item in sample_qs:
            rows.append(_one(item, s, scope, k_eff, answerer,
                             ingest_ms_once=ingest_ms, strategy=strategy))
            ingest_ms = 0.0
        s.close()

    # -- MHR (single shared corpus → one Stele, all queries)
    if mhr_items_list:
        s, ns = _fresh("mhr-judge")
        scope = MemoryScope(namespace=ns)
        t0 = time.perf_counter()
        _ingest_mhr(s, scope, mhr_items_list[0])
        ingest_ms = (time.perf_counter() - t0) * 1000
        for item in mhr_items_list:
            rows.append(_one(item, s, scope, k_eff, answerer,
                             ingest_ms_once=ingest_ms, strategy=strategy))
            ingest_ms = 0.0
        s.close()

    # -- LME (per-question isolated)
    for i, item in enumerate(lme_items_list):
        s, ns = _fresh(f"lme-judge-{i}")
        scope = MemoryScope(namespace=ns)
        t0 = time.perf_counter()
        _ingest_lme(s, scope, item)
        ingest_ms = (time.perf_counter() - t0) * 1000
        rows.append(_one(item, s, scope, k_eff, answerer,
                         ingest_ms_once=ingest_ms, strategy=strategy))
        s.close()

    # -- LongBench (per-record isolated)
    for i, item in enumerate(longbench_items_list):
        s, ns = _fresh(f"{item['benchmark']}-{i}")
        scope = MemoryScope(namespace=ns)
        t0 = time.perf_counter()
        _ingest_longbench(s, scope, item)
        ingest_ms = (time.perf_counter() - t0) * 1000
        rows.append(_one(item, s, scope, k_eff, answerer,
                         ingest_ms_once=ingest_ms, strategy=strategy))
        s.close()

    # -- RAGBench (per-record isolated)
    for i, item in enumerate(ragbench_items_list):
        s, ns = _fresh(f"{item['benchmark']}-{i}")
        scope = MemoryScope(namespace=ns)
        t0 = time.perf_counter()
        _ingest_ragbench(s, scope, item)
        ingest_ms = (time.perf_counter() - t0) * 1000
        rows.append(_one(item, s, scope, k_eff, answerer,
                         ingest_ms_once=ingest_ms, strategy=strategy))
        s.close()

    return _summarize(rows, profile=profile, spec=spec, k_eff=k_eff)


def _one(item: dict[str, Any], s: Stele, scope: MemoryScope, k: int,
         answerer: OpenAICompatAnswerer,
         *, ingest_ms_once: float,
         strategy: str | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    recall_kwargs: dict[str, Any] = {
        "query": item["question"], "scope": scope, "max_memory_hits": k,
    }
    if strategy:
        recall_kwargs["strategy"] = strategy
    rr = s.recall(**recall_kwargs)
    recall_ms = (time.perf_counter() - t0) * 1000
    context, hits = _build_context(rr)
    prompt_tokens = _estimate_tokens(item["question"]) + _estimate_tokens(context)

    t0 = time.perf_counter()
    try:
        answer, completion_tokens = answerer.answer(
            question=item["question"], context=context,
            expected_answer=item["expected"],
        )
    except Exception as e:  # noqa: BLE001
        return {**_meta(item), "error": f"answer: {e}", "recall_ms": recall_ms,
                "ingest_ms_once": ingest_ms_once}
    answer_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        verdict = answerer.judge(
            question=item["question"], expected_answer=item["expected"],
            answer=answer, context=context,
        )
    except Exception as e:  # noqa: BLE001
        return {**_meta(item), "error": f"judge: {e}", "recall_ms": recall_ms,
                "answer_ms": answer_ms, "ingest_ms_once": ingest_ms_once}
    judge_ms = (time.perf_counter() - t0) * 1000

    return {
        **_meta(item),
        "ingest_ms_once": ingest_ms_once,
        "recall_ms": round(recall_ms, 1),
        "answer_ms": round(answer_ms, 1),
        "judge_ms": round(judge_ms, 1),
        "recall_hits": hits,
        "context": context,
        "context_chars": len(context),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "answer": answer,
        "correct": bool(verdict.correct),
        "sufficient": bool(verdict.sufficient),
        "confidence": float(verdict.confidence),
        "rationale": str(verdict.rationale)[:500],
    }


def _meta(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark": item["benchmark"],
        "question": item["question"][:200],
        "expected": item["expected"][:200],
    }


def _summarize(rows: list[dict[str, Any]], *, profile: str,
               spec: dict[str, Any], k_eff: int) -> dict[str, Any]:
    by_bench: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_bench.setdefault(r["benchmark"], []).append(r)
    per_bench = []
    for bench, rs in sorted(by_bench.items()):
        scored = [r for r in rs if "correct" in r]
        if not scored:
            per_bench.append({"benchmark": bench, "scored": 0,
                              "errors": [r.get("error") for r in rs]})
            continue
        correct = sum(1 for r in scored if r["correct"])
        recall_ms = [r["recall_ms"] for r in scored]
        answer_ms = [r["answer_ms"] for r in scored]
        judge_ms = [r["judge_ms"] for r in scored]
        tokens = [r["total_tokens"] for r in scored]
        per_bench.append({
            "benchmark": bench,
            "n": len(scored),
            "accuracy_pct": round(100 * correct / len(scored), 1),
            "recall_ms_p50": round(median(recall_ms), 1),
            "recall_ms_p95": round(_percentile(recall_ms, 95), 1),
            "answer_ms_p50": round(median(answer_ms), 1),
            "answer_ms_p95": round(_percentile(answer_ms, 95), 1),
            "judge_ms_p50": round(median(judge_ms), 1),
            "total_tokens_mean": round(mean(tokens), 0),
            "total_tokens_p95": round(_percentile(tokens, 95), 0),
            "recall_hits_mean": round(mean(r["recall_hits"] for r in scored), 1),
        })
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": profile,
        "profile_notes": spec.get("notes", ""),
        "k": k_eff,
        "per_benchmark": per_bench,
        "rows": rows,
    }


def _md(report: dict[str, Any]) -> str:
    lines = [
        "# Stele — LLM-judged + Timed Third-Party Lane",
        "",
        f"Generated: {report['timestamp']}  ·  Profile: `{report['profile']}`  ·  k={report['k']}",
        "",
        f"> {report['profile_notes']}",
        "",
        "## Per-benchmark headline",
        "",
        (
            "| Benchmark | n | Accuracy | recall p50/p95 (ms) | "
            "answer p50/p95 (ms) | judge p50 (ms) | tokens mean/p95 | hits |"
        ),
        "|---|---:|---:|---|---|---:|---|---:|",
    ]
    for b in report["per_benchmark"]:
        if not b.get("n"):
            lines.append(f"| {b['benchmark']} | — | **ERRORS** | — | — | — | — | — |")
            continue
        lines.append(
            f"| {b['benchmark']} | {b['n']} | **{b['accuracy_pct']}%** | "
            f"{b['recall_ms_p50']}/{b['recall_ms_p95']} | "
            f"{b['answer_ms_p50']}/{b['answer_ms_p95']} | "
            f"{b['judge_ms_p50']} | "
            f"{int(b['total_tokens_mean'])}/{int(b['total_tokens_p95'])} | "
            f"{b['recall_hits_mean']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="hybrid-best",
                    choices=sorted(harness.PROFILES.keys()))
    ap.add_argument("--openai-base-url",
                    default=os.environ.get("OPENAI_BASE_URL",
                                           "http://192.168.1.193:8000/v1"))
    ap.add_argument("--openai-api-key",
                    default=os.environ.get("OPENAI_API_KEY", "not-needed"))
    ap.add_argument("--model",
                    default="Intel/Qwen3-Coder-Next-int4-AutoRound")
    ap.add_argument("--label",
                    help="Suffix on output dir (e.g. 'gpt5mini'). Default: model slug.")
    ap.add_argument("--max-locomo", type=int, default=15)
    ap.add_argument("--max-mhr", type=int, default=15)
    ap.add_argument("--max-lme", type=int, default=15)
    ap.add_argument("--max-longbench-per-task", type=int, default=5)
    ap.add_argument("--max-ragbench-per-subset", type=int, default=5)
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    a = ap.parse_args()

    answerer = OpenAICompatAnswerer(
        answer_model=a.model, judge_model=a.model,
        base_url=a.openai_base_url, api_key=a.openai_api_key,
    )

    report = run_judge_lane(
        profile=a.profile, answerer=answerer,
        max_locomo=a.max_locomo, max_mhr=a.max_mhr, max_lme=a.max_lme,
        max_longbench_per_task=a.max_longbench_per_task,
        max_ragbench_per_subset=a.max_ragbench_per_subset, k=a.k,
    )

    label = a.label or (a.model.split("/")[-1].lower()
                        .replace(":", "-").replace("_", "-"))
    out_dir = a.output_root / datetime.now(UTC).strftime("%Y-%m-%d") / \
        f"judge-lane-{a.profile}-{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "Report.md").write_text(_md(report))
    print(_md(report))


if __name__ == "__main__":
    main()

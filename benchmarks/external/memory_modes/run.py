# ruff: noqa: E501,SIM105,SIM113 -- benchmark helper.
"""Shared runner for the memory-modes benchmark.

Iterates `modes x sources x cases x conditions`, owns the answerer/judge wiring
and the namespace lifecycle, aggregates, and writes one additive JSON under
benchmarks/runs/cq-additive/. Modes never touch the network or write files.

Run:
  STELE_PG_DSN=postgresql://... \
    .venv/bin/python -m benchmarks.external.memory_modes.run \
      --modes guardrail_adherence --per-corpus 5
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_shootout import _answer
from benchmarks.external.memory_modes.base import Mode, RunCtx
from benchmarks.external.memory_modes.registry import MODES
from benchmarks.external.sweep_matrix import _GEMMA, _QWEN
from stele.core.artifact import estimate_tokens
from stele.core.config import (
    BackendConfig,
    IndexingConfig,
    RetrievalConfig,
    StashConfig,
)
from stele.core.stash import Stele

_ANSWER_URL = "http://192.168.1.193:8000/v1"
_JUDGE_URL = "http://192.168.1.133:8000/v1"


def _load_rejudge() -> Any:
    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rj)
    return rj


def _store(dsn: str, memory_vector: bool) -> Stele:
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="skip"),
        retrieval=RetrievalConfig(default_mode="hybrid", memory_vector=memory_vector),
    ))


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean of every numeric per-condition field, keyed mode -> source -> condition."""
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        for cond, vals in r["conditions"].items():
            buckets[(r["mode"], r["source"], cond)].append(vals)
    agg: dict[str, Any] = {}
    for (mode, source, cond), entries in buckets.items():
        means: dict[str, float] = {}
        for key in entries[0]:
            nums = [e[key] for e in entries if isinstance(e[key], (int, float)) and not isinstance(e[key], bool)]
            if nums:
                means[key] = round(sum(nums) / len(nums), 4)
        means["n"] = len(entries)
        agg.setdefault(mode, {}).setdefault(source, {})[cond] = means
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=[m.name for m in MODES])
    ap.add_argument("--sources", nargs="+", default=["synthetic"],
                    choices=["synthetic", "real_trace"])
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--memory-vector", action="store_true")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cq-additive"))
    ap.add_argument("--dsn", default=os.environ.get("STELE_PG_DSN"))
    args = ap.parse_args()
    if not args.dsn:
        raise SystemExit("set STELE_PG_DSN or pass --dsn")

    ans = OpenAICompatAnswerer(
        answer_model=_QWEN, judge_model=_GEMMA,
        base_url=_ANSWER_URL, api_key="local",
        judge_base_url=_JUDGE_URL, judge_api_key="local",
    )
    judge_fn: Callable[[str, str, str], bool] | None = None
    if not args.no_judge:
        rj = _load_rejudge()
        judge_ans = OpenAICompatAnswerer(
            answer_model=_GEMMA, judge_model=_GEMMA,
            base_url=_JUDGE_URL, api_key="local",
        )

        def _judge(question: str, expected: str, answer: str) -> bool:
            return bool(rj._jscore_correct(judge_ans, question=question,
                                           expected=expected, answer=answer))

        judge_fn = _judge

    ctx = RunCtx(
        answer=lambda c, q: _answer(ans, c, q),
        complete=lambda p: str(ans._chat(model=_QWEN, json_mode=False,
                                         messages=[{"role": "user", "content": p}])).strip(),
        judge=judge_fn,
        count_tokens=lambda t: int(estimate_tokens(t)),
        memory_vector=args.memory_vector,
    )

    modes: list[Mode] = [m for m in MODES if m.name in args.modes]
    rows: list[dict[str, Any]] = []
    for mode in modes:
        for source in args.sources:
            cases = mode.corpus(source, args.per_corpus, args.seed)
            if not cases:
                print(f"[{mode.name}/{source}] no cases (mode supplies none for this source); skip", flush=True)
                continue
            store = _store(args.dsn, args.memory_vector)
            ns = f"memmode-{mode.name}-{source}"
            try:
                store.purge_namespace(ns)
            except Exception:
                pass
            mode.populate(store, cases)
            print(f"[{mode.name}/{source}] populated {len(cases)} cases", flush=True)
            done = 0
            for case in cases:
                rec: dict[str, Any] = {
                    "mode": mode.name, "source": source, "case": case.case_id,
                    "question": case.question, "gold": case.gold, "conditions": {},
                }
                for cond in mode.conditions:
                    res = mode.run_case(store, case, cond, ctx)
                    metric = mode.score(case, res)
                    rec["conditions"][cond] = {
                        **metric, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                        "deterministic": res.deterministic,
                        **{k: v for k, v in res.extra.items() if isinstance(v, (int, float, str))},
                    }
                rows.append(rec)
                done += 1
                if done % 5 == 0:
                    print(f"  {mode.name}/{source}: {done}/{len(cases)} cases", flush=True)
            store.close()
            print(f"[{mode.name}/{source}] done", flush=True)

    agg = _aggregate(rows)
    print("\n=== MEMORY MODES ===")
    for mname in sorted(agg):
        for src in sorted(agg[mname]):
            print(f"\n{mname} / {src}:")
            for cond, m in agg[mname][src].items():
                head = " ".join(f"{k}={v}" for k, v in m.items()
                                if k not in ("tokens_out", "rules_carried"))
                print(f"  {cond:16s} {head}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"multimode-{stamp}.json"
    f.write_text(json.dumps({
        "config": "memory-modes / access-pattern x source x condition / deterministic-headline",
        "stamp": stamp,
        "endpoints": {"answer": _ANSWER_URL, "judge": _JUDGE_URL},
        "modes": [m.name for m in modes],
        "memory_vector": args.memory_vector,
        "agg": agg, "rows": rows,
    }, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

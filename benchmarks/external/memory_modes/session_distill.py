# ruff: noqa: E501 -- session-distillation harness.
"""Distill durable memory from REAL agent transcripts at scale, then run the six
distill views. The honest target the curated-CLAUDE.md path was a poor proxy for.

Transcript parsing + LLM extraction are first-class core now
(`stele.extraction.session` / `Stele.extract.from_session`); this harness only
picks sessions, drives ingestion in resumable batches, and prints the views.

Run:
    STELE_PG_DSN=postgresql://.../stele_bench \
      .venv/bin/python -m benchmarks.external.memory_modes.session_distill \
        --limit 40 --per-session-windows 3 --distill
Resume in buckets with --start (and --no-purge to accumulate).
"""

from __future__ import annotations

import argparse
import contextlib
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele
from stele.distill.jobs import run_sync
from stele.distill.models import DistilledView

_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


def _sessions(limit: int, start: int = 0) -> list[Path]:
    """Diverse-first, paginated. One largest session per project first (breadth),
    then the remainder by size, then slice [start:start+limit]. `start` makes
    large runs resumable in buckets without re-ingesting earlier sessions."""
    files = sorted(_PROJECTS_ROOT.glob("*/*.jsonl"), key=lambda p: -p.stat().st_size)
    seen: set[str] = set()
    head: list[Path] = []
    tail: list[Path] = []
    for f in files:
        (head if f.parent.name not in seen else tail).append(f)
        seen.add(f.parent.name)
    return (head + tail)[start : start + limit]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--limit", type=int, default=20, help="how many sessions to ingest")
    ap.add_argument("--start", type=int, default=0, help="session offset (resume/batch in buckets)")
    ap.add_argument("--per-session-windows", type=int, default=3)
    ap.add_argument("--namespace", default="distill-real-sessions")
    ap.add_argument("--no-purge", action="store_true", help="accumulate into the namespace (resumed batches)")
    ap.add_argument("--distill", action="store_true", help="render the six views after ingest")
    args = ap.parse_args(argv)
    dsn = args.dsn or os.environ.get("STELE_PG_DSN")
    if not dsn:
        raise SystemExit("set STELE_PG_DSN or pass --dsn")

    from benchmarks.answer_workflow import OpenAICompatAnswerer
    from benchmarks.external.memory_modes.run import _ANSWER_URL
    from benchmarks.external.sweep_matrix import _QWEN
    from stele.core.config import BackendConfig, StashConfig

    stele = Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn)))
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_QWEN, base_url=_ANSWER_URL, api_key="local")

    def llm(prompt: str) -> str:
        return str(ans._chat(model=_QWEN, json_mode=False,
                             messages=[{"role": "user", "content": prompt}])).strip()

    stele._distill_llm = llm  # type: ignore[attr-defined]
    scope = MemoryScope(namespace=args.namespace)
    if args.start == 0 and not args.no_purge:
        with contextlib.suppress(Exception):
            stele.purge_namespace(args.namespace, dry_run=False)

    sessions = _sessions(args.limit, args.start)
    total = 0
    for i, path in enumerate(sessions, start=args.start):
        rep = stele.extract.from_session(transcript=path, scope=scope, llm=llm,
                                         max_windows=args.per_session_windows)
        total += rep.stats.accepted_count
        print(f"  [{i}] ingested {rep.stats.accepted_count:>3} memories from {path.parent.name[:34]}", flush=True)
    print(f"\nTOTAL this batch: {total} durable memories from {len(sessions)} sessions (offset {args.start})\n", flush=True)
    if not args.distill:
        print("(ingest-only; pass --distill to render the views)")
        return 0

    def _factory(mode: str) -> Callable[[], Coroutine[Any, Any, DistilledView]]:
        def _call() -> Coroutine[Any, Any, DistilledView]:
            return getattr(stele.distill, mode)(scope)  # type: ignore[no-any-return]
        return _call

    for mode in ("rules", "skills", "best_practices", "precedents", "facts"):
        view = run_sync(_factory(mode))
        print(f"=== distill_{mode} -> {len(view.items)} ===")
        for it in view.items[:8]:
            do_instead = getattr(it, "do_instead", "")
            extra = f"  ==> {do_instead}" if do_instead else ""
            print(f"   - {it.summary[:88]}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

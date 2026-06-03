# ruff: noqa: E501 -- fleet orchestrator.
"""Distill memory from real transcripts across a POOL of LLM endpoints, sized to
the topology: a light laptop dispatcher fanning bounded concurrency out to two
resource-limited Spark endpoints (one model each). The work is I/O-bound (the
laptop waits on the Sparks), so threads-blocked-on-network is cheap on bento;
the throughput ceiling is the Sparks, so concurrency is CAPPED per endpoint at
its measured batching sweet spot (Qwen ~4, Gemma ~8+).

Streaming + resumable: sessions flow through a queue, each committed as it
finishes (from_session commits to postgres), so a sleep/restart resumes via
--start. Each worker owns its own Stele (own DB connection) for thread safety.

Run:
    STELE_PG_DSN=postgresql://.../stele_bench \
      .venv/bin/python -m benchmarks.external.memory_modes.distill_fleet \
        --limit 200 --windows 1 --namespace distill-fleet
"""

from __future__ import annotations

import argparse
import contextlib
import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.memory_modes.session_distill import _sessions
from stele.core.config import BackendConfig, StashConfig
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele

# (name, base_url, model, concurrency cap). Caps from the headroom probe:
# Qwen saturates ~4, Gemma still scales at 8. Tune per your endpoints.
ENDPOINTS: list[tuple[str, str, str, int]] = [
    ("qwen", "http://192.168.1.193:8000/v1", "Intel/Qwen3-Coder-Next-int4-AutoRound", 4),
    ("gemma", "http://192.168.1.133:8000/v1", "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit", 8),
]


def _make_llm(ans: OpenAICompatAnswerer, model: str) -> Callable[[str], str]:
    def llm(p: str) -> str:
        return str(ans._chat(model=model, json_mode=False,
                             messages=[{"role": "user", "content": p}])).strip()
    return llm


def _worker(name: str, stele: Stele, llm: Callable[[str], str], ns: str,
            q: queue.Queue[Path], stats: dict[str, int],
            lock: threading.Lock, windows: int) -> None:
    """One endpoint slot: its Stele (own DB connection, built serially upfront to
    avoid a concurrent schema-init race) + an LLM bound to its endpoint. Pulls
    sessions until the queue drains."""
    scope = MemoryScope(namespace=ns)
    while True:
        try:
            path = q.get_nowait()
        except queue.Empty:
            return
        n = 0
        try:
            rep = stele.extract.from_session(transcript=path, scope=scope, llm=llm, max_windows=windows)
            n = rep.stats.accepted_count
        except Exception as e:  # noqa: BLE001 -- one bad session must not kill the worker
            print(f"  [{name}] ERROR on {path.name[:18]}: {repr(e)[:80]}", flush=True)
        with lock:
            stats["mem"] += n
            stats["done"] += 1
            d = stats["done"]
        print(f"  [{name}] {d}/{stats['total']}  {path.parent.name[:26]} -> {n} mem", flush=True)
        q.task_done()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--windows", type=int, default=1, help="windows/session (1 for small sessions)")
    ap.add_argument("--namespace", default="distill-fleet")
    ap.add_argument("--no-purge", action="store_true")
    args = ap.parse_args(argv)
    dsn = args.dsn or os.environ.get("STELE_PG_DSN")
    if not dsn:
        raise SystemExit("set STELE_PG_DSN or pass --dsn")

    if args.start == 0 and not args.no_purge:
        admin = Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn)))
        with contextlib.suppress(Exception):
            admin.purge_namespace(args.namespace, dry_run=False)

    sessions = _sessions(args.limit, args.start)
    q: queue.Queue[Path] = queue.Queue()
    for p in sessions:
        q.put(p)
    stats = {"mem": 0, "done": 0, "total": len(sessions)}
    lock = threading.Lock()
    total_slots = sum(cap for _, _, _, cap in ENDPOINTS)
    print(f"fleet: {len(sessions)} sessions over {len(ENDPOINTS)} endpoints, {total_slots} concurrent slots, {args.windows} window(s)/session\n", flush=True)

    # Build each slot's Stele SERIALLY up front: concurrent first-connect runs
    # guarded schema DDL and races otherwise (observed: workers dying on init).
    slots: list[tuple[str, Stele, Callable[[str], str]]] = []
    for name, url, model, cap in ENDPOINTS:
        for _ in range(cap):
            stele = Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn)))
            ans = OpenAICompatAnswerer(answer_model=model, judge_model=model, base_url=url, api_key="local")
            slots.append((name, stele, _make_llm(ans, model)))

    t0 = time.monotonic()
    threads: list[threading.Thread] = []
    for name, stele, llm in slots:
        th = threading.Thread(target=_worker, args=(name, stele, llm, args.namespace, q, stats, lock, args.windows), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    dt = time.monotonic() - t0
    rate = len(sessions) / dt if dt else 0.0
    print(f"\nFLEET DONE: {stats['mem']} memories from {len(sessions)} sessions in {dt:.0f}s "
          f"({rate * 60:.1f} sessions/min, {dt / max(len(sessions), 1):.1f}s/session effective). "
          f"Full corpus (5710) at this rate: {5710 / rate / 3600:.1f}h" if rate else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

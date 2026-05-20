"""Bulk-write microbenchmark — store_many vs per-row store across backends.

Acceptance bar from issue #14: ≥5× speedup on postgres at N=1000 batches
against the per-row baseline. Other backends report side-by-side for
operator transparency.

Usage:
    .venv/bin/python -m benchmarks.bulk_write           # memory + sqlite
    STELE_PG_DSN=postgresql://... .venv/bin/python -m benchmarks.bulk_write

Output: one markdown row per backend with (rows, per_row_secs,
bulk_secs, speedup_x). Returns non-zero exit code if the postgres
target falls below 5×.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from stele import Stele
from stele.core.artifact import StoreRequest

BATCH_SIZES = (100, 500, 1000)
POSTGRES_SPEEDUP_TARGET = 5.0


def _stele_for_backend(tmp: Path, backend: str) -> Stele:
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp / f"bench_{uuid.uuid4().hex}.db")}}
        )
    if backend == "postgres":
        return Stele.from_config(
            {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}}
        )
    raise ValueError(f"unknown backend: {backend}")


def _measure(stele: Stele, n: int, *, namespace: str, use_bulk: bool) -> float:
    items = [
        StoreRequest(content=f"benchrow {i} {namespace}", namespace=namespace)
        for i in range(n)
    ]
    start = time.perf_counter()
    if use_bulk:
        stele.store_many(items)
    else:
        for item in items:
            stele.store(
                item.content,
                namespace=item.namespace,
                session_id=item.session_id,
                metadata=item.metadata or None,
                lifecycle=item.lifecycle,
                ttl_seconds=item.ttl_seconds,
            )
    return time.perf_counter() - start


def _run_backend(backend: str) -> list[tuple[int, float, float, float]]:
    results: list[tuple[int, float, float, float]] = []
    with TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for n in BATCH_SIZES:
            ns_a = f"perrow_{uuid.uuid4().hex[:8]}"
            ns_b = f"bulk_{uuid.uuid4().hex[:8]}"
            # Per-row baseline.
            stele = _stele_for_backend(tmp, backend)
            per_row = _measure(stele, n, namespace=ns_a, use_bulk=False)
            stele.close()
            # Bulk path.
            stele = _stele_for_backend(tmp, backend)
            bulk = _measure(stele, n, namespace=ns_b, use_bulk=True)
            stele.close()
            speedup = per_row / bulk if bulk > 0 else float("inf")
            results.append((n, per_row, bulk, speedup))
    return results


def _print_markdown(backend: str, rows: list[tuple[int, float, float, float]]) -> None:
    print(f"\n## {backend}\n")
    print("| N | per-row (s) | store_many (s) | speedup |")
    print("|---|---|---|---|")
    for n, per_row, bulk, speedup in rows:
        print(f"| {n} | {per_row:.3f} | {bulk:.3f} | {speedup:.1f}× |")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backends",
        nargs="*",
        default=None,
        help="Subset of backends to run (memory sqlite postgres). Default: all available.",
    )
    args = parser.parse_args(argv)

    backends = ["memory", "sqlite"]
    if os.environ.get("STELE_PG_DSN"):
        backends.append("postgres")
    if args.backends:
        backends = [b for b in backends if b in args.backends]

    print("# Bulk-write microbenchmark\n")
    print(f"Measuring store_many vs per-row store across batch sizes {BATCH_SIZES}.")
    print("Per-row includes one transaction per row; bulk uses one transaction total.")

    all_results: dict[str, list[tuple[int, float, float, float]]] = {}
    for backend in backends:
        rows = _run_backend(backend)
        all_results[backend] = rows
        _print_markdown(backend, rows)

    # Acceptance gate: postgres ≥5× at N=1000.
    if "postgres" in all_results:
        pg_1k = next(
            (s for n, _, _, s in all_results["postgres"] if n == 1000), None
        )
        if pg_1k is not None:
            print(f"\nPostgres N=1000 speedup: {pg_1k:.1f}× (target ≥{POSTGRES_SPEEDUP_TARGET}×)")
            if pg_1k < POSTGRES_SPEEDUP_TARGET:
                print("FAIL: postgres speedup below target", file=sys.stderr)
                return 1
            print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

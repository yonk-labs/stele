# ruff: noqa: E501 -- demo helper.
"""End-to-end distillation demo: seed gold memories, run all six distillers,
score against hand-sorted gold, and print a human-readable summary.

Usage::

    # in-memory backend (no external services required)
    .venv/bin/python -m benchmarks.external.memory_modes.distill_demo

    # postgres backend, pre-populated namespace (skip seed step)
    .venv/bin/python -m benchmarks.external.memory_modes.distill_demo \\
        --dsn postgresql://yonk:yonk@localhost:55432/stele \\
        --namespace myns --no-seed
"""
from __future__ import annotations

import argparse
from typing import cast

from benchmarks.external.memory_modes.distill_gold import GOLD, score_view
from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.distill.jobs import run_sync
from stele.distill.models import DistilledView


def seed_gold_memories(stele: Stele, ns: str) -> None:
    """Populate *stele* with memories that mirror the GOLD shape.

    Each memory needs a real stele:// source_ref, so we store a small
    artifact for every item first, then cite it.  No lede / postgres
    required -- the memory backend handles everything.
    """
    scope = MemoryScope(namespace=ns)

    def _ref(text: str) -> str:
        return str(stele.store(text, namespace=ns).reference)

    for g in GOLD["facts"]:
        stele.memory.add(
            text=g["text"],
            kind="fact",
            source_refs=[_ref(g["text"])],
            scope=scope,
            summary=f"{g['id']}: {g['text']}",
            metadata={"project": g["id"]},
        )

    for g in GOLD["precedents"]:
        stele.memory.add(
            text=g["query"],
            kind="decision",
            source_refs=[_ref(g["query"])],
            scope=scope,
            summary=g["query"],
            metadata={"sha": g["id"]},
        )

    for g in GOLD["skills"]:
        stele.memory.add(
            text=g["text"],
            kind="instruction",
            source_refs=[_ref(g["text"])],
            scope=scope,
            summary=g["text"],
            metadata={"id": g["id"]},
        )

    for g in GOLD["best_practices"]:
        stele.memory.add(
            text=g["text"],
            kind="preference",
            source_refs=[_ref(g["text"])],
            scope=scope,
            summary=g["text"],
            metadata={"id": g["id"]},
        )

    for g in GOLD["rules"]:
        stele.memory.add(
            text=f"{g['dont']} (outdated/forbidden)",
            kind="pitfall",
            source_refs=[_ref(g["dont"])],
            scope=scope,
            summary=g["dont"],
            metadata={"do_instead": g["do_instead"], "domain": g["domain"]},
        )

    # State: superseded (old head) -> active (terminal head) per entity.
    for g in GOLD["state"]:
        first = stele.memory.add(
            text=f"{g['id']} started",
            kind="decision",
            source_refs=[_ref(g["id"])],
            scope=scope,
            summary=g["id"],
            metadata={"entity": g["id"]},
        )
        terminal_text = {
            "done": "shipped to prod, complete",
            "abandoned": "retracted, descoped",
            "in_progress": "still in progress",
        }.get(g["gold"], "in progress")
        stele.memory.add(
            text=f"{g['id']}: {terminal_text}",
            kind="decision",
            source_refs=[_ref(g["id"])],
            scope=scope,
            summary=g["id"],
            metadata={"entity": g["id"]},
            supersedes=[first.record.id],
        )


def distill_all(stele: Stele, ns: str) -> dict[str, DistilledView]:
    """Run all six distillers synchronously and return {mode: DistilledView}."""
    scope = MemoryScope(namespace=ns)
    results: dict[str, DistilledView] = {}
    for mode in ("facts", "precedents", "state", "skills", "best_practices", "rules"):
        async def _run(m: str = mode) -> DistilledView:  # noqa: RUF006
            return cast(DistilledView, await getattr(stele.distill, m)(scope))

        results[mode] = run_sync(_run)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Seed gold memories, distill, and score against hand-sorted gold."
    )
    ap.add_argument("--namespace", default="distill-demo", help="Memory namespace to use")
    ap.add_argument("--dsn", default=None, help="Postgres DSN; omit for in-memory backend")
    ap.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip seeding (use when pointing at an already-populated namespace)",
    )
    args = ap.parse_args(argv)

    cfg: dict[str, object] = (
        {"backend": {"type": "postgres", "dsn": args.dsn}}
        if args.dsn
        else {"backend": {"type": "memory"}}
    )
    stele = Stele.from_config(cfg)

    if not args.no_seed:
        print(f"Seeding gold memories into namespace '{args.namespace}'...")
        seed_gold_memories(stele, args.namespace)
        print("  done.\n")

    print("Running distillers...")
    views = distill_all(stele, args.namespace)

    for mode, view in views.items():
        print(f"\n=== {mode} (n={len(view.items)}, used_llm={view.used_llm}) ===")
        for it in view.items[:8]:
            extra = (
                f"  -> {getattr(it, 'do_instead', '')}"
                if getattr(it, "do_instead", "")
                else ""
            )
            print(f"  - {it.summary[:80]}{extra}")

        # Score modes where we can extract IDs from the summary prefix.
        if mode in GOLD:
            if mode == "rules":
                ids = [getattr(it, "dont", it.summary) for it in view.items]
            elif mode == "state":
                ids = [it.summary for it in view.items]
            else:
                ids = [it.summary.split(":")[0].strip() for it in view.items]
            scores = score_view(mode, ids)
            print(
                f"  gold scores: recall={scores['recall']:.2f}  "
                f"precision={scores['precision']:.2f}  "
                f"hit@1={scores['hit_at_1']:.2f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

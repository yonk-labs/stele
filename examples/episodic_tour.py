"""Episodic recall tour: ingest a few past sessions, then read them back as
episodes, a timeline, cross-session spans, and via episodic recall.

Run it:  .venv/bin/python examples/episodic_tour.py

Self-contained (in-memory backend, no network, no DSN). Dates are relative to
"now" so the "last week" query lands; the structure of the output is stable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.storage.memory_store._embedder import build_memory_embedder


def _session(stele, scope, *, sid, when, text, decisions, pitfalls):
    """Store one past session (a reduced-session artifact) + the memories it
    produced, exactly as the ingest feed + distillation would."""
    ref = str(
        stele.store(
            text,
            namespace=scope.namespace,
            session_id=sid,
            metadata={"source": "session-ingest", "session_mtime": when.isoformat()},
        ).reference
    )
    for d in decisions:
        stele.memory.add(text=d, kind="decision", source_refs=[ref], scope=scope, summary=d)
    for p in pitfalls:
        stele.memory.add(text=p, kind="pitfall", source_refs=[ref], scope=scope, summary=p)
    return ref


def main() -> None:
    stele = Stele.from_config({"backend": {"type": "memory"}})
    # spans cluster by embedding similarity; inject the embedder (deterministic
    # one-episode-per-span fallback when it is None).
    embedder = build_memory_embedder(stele.config.indexing)
    if embedder is not None:
        stele._distill_embedder = embedder

    scope = MemoryScope(namespace="tour")
    now = datetime.now(UTC)

    _session(
        stele, scope, sid="sess-dash-1", when=now - timedelta(days=3),
        text="building the dashboard widget layout and grid",
        decisions=["use a CSS grid for the dashboard widget layout"],
        pitfalls=["widget overflow broke the grid until min-width was set"],
    )
    _session(
        stele, scope, sid="sess-dash-2", when=now - timedelta(days=20),
        text="polishing the dashboard widget styles",
        decisions=["standardize dashboard widget spacing on an 8px scale"],
        pitfalls=[],
    )
    _session(
        stele, scope, sid="sess-auth", when=now - timedelta(days=1),
        text="refactoring the auth token refresh flow",
        decisions=["move token refresh into a single interceptor"],
        pitfalls=["refresh storm when 401s arrived in parallel; added a mutex"],
    )

    def show(title):
        print(f"\n=== {title} ===")

    show("distill.episodes  (one 'what happened' per session, newest-first)")
    for it in asyncio.run(stele.distill.episodes(scope)).items:
        print(f"  [{it.when:%Y-%m-%d}] {it.session_id}: {it.summary}")

    show("distill.timeline(query='dashboard')  (oldest-first narrative, filtered)")
    for it in asyncio.run(stele.distill.timeline(scope, query="dashboard")).items:
        print(f"  [{it.when:%Y-%m-%d}] {it.session_id}: {it.summary}")

    show("distill.spans  (cross-session arcs, clustered by similarity)")
    for s in asyncio.run(stele.distill.spans(scope)).items:
        span = f"{s.started:%Y-%m-%d}..{s.ended:%Y-%m-%d}" if s.started else "?"
        print(f"  span {span}  sessions={s.session_ids}: {s.summary}")

    show("recall.episodic('what was I building last week')")
    result = stele.recall.episodic(query="what was I building last week", scope=scope)
    for h in result.episodes:
        print(f"  [{h.when:%Y-%m-%d}] score={h.score:.2f} {h.session_id}: "
              f"{h.summary}  ({len(h.memories)} memories)")

    stele.close()


if __name__ == "__main__":
    main()

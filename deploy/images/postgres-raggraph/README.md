# postgres-raggraph image (Phase 5 — reserved slot, NOT yet built)

The `graph` / `all` compose profiles reference a `build: .` here. It is a
**documented no-op until Phase 5**. Building it is gated by the Phase 5
Task-0 in `docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md`
and the pg-raggraph changes in `2026-05-17-pg-raggraph-requirements.md`
(PRG-1..PRG-4).

When Phase 5 is scheduled, this directory gets a real `Dockerfile`:
`pgvector/pgvector:pg16` base + the pinned `pg-raggraph` Python package +
its schema bootstrap. Until then, do not run `--profile graph` expecting a
working server; `tests/e2e/test_living_knowledge.py` stays skip-gated on
`STELE_PG_RAGGRAPH_DSN`.

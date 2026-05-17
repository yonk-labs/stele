# postgres-raggraph image (Phase 5 — built)

`pgvector/pgvector:pg16` + an initdb script that creates the `vector`
extension. pg-raggraph (the Python library) runs in the Stele test/host
process, connects here over `STELE_PG_RAGGRAPH_DSN`
(`postgresql://yonk:yonk@localhost:55453/stele`), and **auto-migrates its own
schema** on first connect (`pg_raggraph.db._ensure_schema`). The image only
provides the one prerequisite pg-raggraph does not self-create: the `vector`
extension (`schema.sql:2` — "Extensions must be created before this runs").

Pinned dependency: `pg-raggraph==0.3.0a3` via the Stele `[postgres-graph]`
extra (PRG-1..PRG-4 verified in source — see
`docs/superpowers/specs/2026-05-17-phase5-task0-pg-raggraph-api-recon.md`).

Brought up by `make -C deploy e2e-graph` (compose profile `all`/`graph`,
port 55453).

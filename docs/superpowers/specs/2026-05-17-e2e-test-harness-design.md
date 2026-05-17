---
title: Deployable Full-Stack E2E Test Harness
created: 2026-05-17
status: design-approved (planning only — not yet built)
location: docs/superpowers/specs/ (committed on phase4-chunkshop-indexing)
depends-on: |
  Phase 4 complete (chunk stores + vector/hybrid across 5 backends).
  Phase 5 (pg-raggraph) NOT required to start — the harness reserves a slot
  for it and is built before Phase 5 so Phase 5 can be verified at all.
---

# Deployable Full-Stack E2E Test Harness — Design

## Why this exists (the gap)

Phase 4 shipped chunk stores for 5 backends, but **only memory + sqlite +
postgres were ever exercised end-to-end**. mariadb and clickhouse paths are
DSN-gated skips — structurally complete, **unproven against live servers**.
Phase 5 (pg-raggraph living knowledge) is **unverifiable** today: there is no
graph-enabled Postgres anywhere in the repo's docker assets
(`docker-compose.backends.yml` is plain `pgvector/pgvector:pg16`).

The repo also has no single "bring up the whole stack and prove it works"
entry point — only `docker-compose.postgres.yml`, `docker-compose.backends.yml`,
and a handful of `scripts/*-up.sh`. A new contributor cannot deploy the full
stack and run a real end-to-end verification from one command.

This harness closes the e2e gap, reserves the Phase 5 slot, and doubles as a
**sample deployment** (the user-facing "here's how you actually run this").

## Goals

1. **One command brings up every backend Stele supports**: postgres+pgvector,
   mariadb, clickhouse — plus a **pg-raggraph-enabled Postgres** slot for
   Phase 5 (built when Phase 5 lands; the slot/compose-profile exists now).
2. **The existing DSN-gated contract/e2e tests run for real** against it —
   `tests/contract/test_vector_contract.py`,
   `test_indexing_modes_contract.py`, `tests/unit/storage/test_chunk_store_*`,
   `tests/integration/test_showcase_e2e.py`. No code changes to those tests;
   they already gate on `STELE_PG_DSN` / `STELE_MARIADB_DSN` /
   `STELE_CLICKHOUSE_DSN` — the harness just provides the servers + env.
3. **A dedicated full-journey e2e suite** that exercises the *public* `Stele`
   API across the real stack: store → index (sync+async) → vector/hybrid
   search → fetch → recall, per backend, with assertions on chunk_id
   round-trip, PII non-leakage, and indexing-status transitions.
4. **Sample-deployment framing**: the same compose file + a short README is
   what a real user would copy to self-host. Sovereign defaults (no network
   after image pull + model cache), matching the project's non-negotiables.
5. **CI-runnable**: a `make`/script target that boots the stack, waits on
   healthchecks, runs the gated suites with all DSNs exported, tears down,
   and emits a captured evidence report.

## Non-Goals

- Not a load/perf harness (that's `benchmarks/longrun`, separate).
- Not a Kubernetes/production deployment (compose only; k8s is a later, separate
  concern if ever).
- Does not modify the locked Phase-1 artifact stores or any gated test logic.
- Does not implement Phase 5 — only reserves the pg-raggraph compose profile
  and an xfail/skip-gated e2e placeholder.

## Layout (proposed)

```text
deploy/
  README.md                     # sample-deployment quickstart (user-facing)
  docker-compose.full.yml       # all backends, profiles: core | graph | all
  .env.example                  # STELE_* DSNs for the compose network
  Makefile                      # up / down / e2e / e2e-graph / logs / nuke
  images/
    postgres-raggraph/          # Dockerfile: pgvector + pg-raggraph extension
                                #   (built in Phase 5; stub README until then)
tests/e2e/
  conftest.py                   # session fixtures: wait-for-health, DSN wiring
  test_full_journey.py          # store->index->search->fetch->recall per backend
  test_living_knowledge.py      # Phase 5: supersede/retract/as_of (xfail-gated
                                #   until pg-raggraph wired — see recon sheet)
  evidence/                     # gitignored; captured run reports land here
```

Rationale for `deploy/` (not `docker/` or `sample/`): it is simultaneously the
e2e target AND the sample self-host artifact; `deploy/` reads correctly for
both audiences. `tests/e2e/` keeps the harness-driving tests beside the suite
they extend, consistent with the existing `tests/contract/` +
`tests/integration/` split.

## Components

### `deploy/docker-compose.full.yml`

Supersedes `docker-compose.backends.yml` / `docker-compose.postgres.yml`
(keep those as thin includes or delete after migration — decide at build
time; not a locked file). Compose **profiles**:

| Profile | Services | Purpose |
|---|---|---|
| `core` | postgres(pgvector), mariadb, clickhouse | Phase 1–4 full e2e |
| `graph` | postgres-raggraph | Phase 5 living-knowledge e2e |
| `all` | everything | CI full sweep |

Every service keeps the existing healthcheck pattern (already present in
`docker-compose.backends.yml`) so the harness can `--wait`. Ports match the
current convention (pg 55432, mariadb 53306, clickhouse 58123/59000) so
existing scripts/DSNs keep working. The pg-raggraph Postgres uses a distinct
port (e.g. 55433) so it can run alongside the plain pgvector one.

### `deploy/images/postgres-raggraph/Dockerfile`

A pgvector base + the pg-raggraph extension. **Built in Phase 5** — the
recon-correction sheet's Task-0 gate determines exactly which pg-raggraph
artifact (PyPI `pg-raggraph` is currently `0.3.0a2` alpha; the Rust extension
lives in the `pg-raggraph-extension` sibling). Until then this dir holds a
README documenting the requirement and the `graph` profile is a no-op.

### `tests/e2e/test_full_journey.py`

Parametrized across `[memory, sqlite, postgres, mariadb, clickhouse]` (each
gated on its DSN like the existing contract tests). For each backend, one
test walks the **public API only**:

```
store(content)  ->  indexing_status -> "indexed" (sync) / "queued"->"indexed" (async)
   -> search(ref, q, mode="vector")   : chunk_id == {aid}:{ord}, retrieval_mode="vector"
   -> search(ref, q, mode="hybrid")   : retrieval_mode="hybrid"
   -> fetch(ref)                       : PII scrubbed, no raw leak
   -> recall(query, scope, strategy="artifact_search")  : strategy_used correct
```

Assertions reuse the Phase 4 invariants (no chunkshop-native objects escape;
PII boundary; `aid:ord` round-trip). This is the artifact that finally proves
mariadb + clickhouse e2e for real.

### `tests/e2e/test_living_knowledge.py`

Phase 5 placeholder. Encodes the *Verification Bar* from
`docs/sovereign-memory-system-plan.md` (supersede / retract / `as_of` /
`version_filter` / every hit cites `stele://`). `pytest.mark.xfail` (strict)
or skip-gated on the `graph` profile + a `STELE_PG_RAGGRAPH_DSN` env until
Phase 5 wires the Revisor. Writing it now locks the acceptance bar before
implementation (the inverse of the Phase 4 fiction problem).

### `deploy/Makefile` / script targets

```
make -C deploy up            # core profile, wait for health
make -C deploy up-all        # core + graph
make -C deploy e2e           # up core -> export DSNs -> pytest tests/e2e + gated
                             #   contract/integration -> capture evidence -> down
make -C deploy e2e-graph     # Phase 5: up graph -> living-knowledge suite
make -C deploy nuke          # down -v (volumes too)
```

`e2e` writes a captured report to `tests/e2e/evidence/<date>/` (gitignored,
same pattern as `benchmarks/runs/`) citing pass/skip counts per backend — the
permanent answer to "what was tested e2e".

## Data flow (verification)

```
make e2e
  -> docker compose --profile core up -d --wait        (healthchecks gate readiness)
  -> export STELE_PG_DSN / STELE_MARIADB_DSN / STELE_CLICKHOUSE_DSN
  -> scripts/chunkshop-setup.sh                          (model cache, offline-safe)
  -> pytest tests/e2e tests/contract tests/integration -q
       (DSN-gated suites now RUN for real on all 5 backends)
  -> write tests/e2e/evidence/<date>/E2E-Report.md
  -> docker compose --profile core down
```

## Error handling / edge cases

- **Healthcheck timeout**: harness fails loud with the failing service's logs;
  never runs tests against a half-up stack (no silent skips).
- **Port collision** with an already-running dev stack: documented; graph
  Postgres on a separate port; `make nuke` for a clean slate.
- **Model not cached**: `chunkshop-setup.sh` runs first; `HF_HUB_OFFLINE=1`
  documented for air-gapped CI.
- **A backend image pull fails in CI**: that profile's tests **fail**, not
  skip — the whole point is to remove false green. (Local dev may still use
  DSN-absent skips; CI sets all DSNs so skips there are a failure signal.)
- **clickhouse/mariadb vector semantics differ**: assertions test the Stele
  contract (chunk_id, retrieval_mode, score in [0,1]), not native SQL — same
  posture as the Phase 4 unit tests.

## Testing the harness itself

- `tests/e2e/conftest.py` health-wait helper unit-tested with a fake docker
  status (no daemon needed).
- A `--dry-run` make target that validates compose config + profiles without
  pulling images (CI lint).
- The e2e suite is excluded from the default `pytest` run (marker
  `@pytest.mark.e2e` + `addopts` deselect) so the fast unit/contract loop
  stays fast; CI opts in explicitly.

## Success criteria

- **HC-1**: `make -C deploy e2e` on a clean machine boots core stack, runs the
  gated contract + integration + `tests/e2e/test_full_journey.py` suites with
  **mariadb and clickhouse exercised for real** (no DSN skips), tears down,
  and writes an evidence report.
- **HC-2**: `tests/e2e/test_full_journey.py` proves the public-API journey
  (store→index→vector/hybrid→fetch→recall) on all 5 backends with the Phase 4
  invariants asserted.
- **HC-3**: `graph` profile + `tests/e2e/test_living_knowledge.py` exist and
  are xfail/skip-gated, encoding the Phase 5 Verification Bar before Phase 5
  is built.
- **HC-4**: `deploy/README.md` is a working sample self-host quickstart; the
  sovereign non-negotiables (no runtime network beyond config; model cache
  pre-stage) hold.
- **HC-5**: default `pytest` runtime is unchanged (e2e deselected by default);
  CI has an explicit `e2e` job.
- **HC-6**: no locked Phase-1 file and no existing gated-test logic modified.

## Out of scope

- pg-raggraph image contents (Phase 5 / its recon Task-0 gate).
- k8s/helm, cloud deployment, TLS, multi-node.
- Perf/load (separate `longrun`).
- Replacing the fast unit-test loop.

## Open decisions (for the implementation plan, not now)

- Keep `docker-compose.backends.yml` as a compatibility shim or migrate
  `scripts/*-up.sh` to the new compose + delete the old files.
- Whether `tests/e2e` reruns the *whole* contract suite or a curated e2e
  subset (CI time vs coverage).
- Evidence-report format reuse from `benchmarks/runs` tooling vs a small
  dedicated reporter.

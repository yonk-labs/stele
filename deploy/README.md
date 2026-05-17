# Stele — Full-Stack Deployment & E2E Harness

This is both the **end-to-end test target** and a **sample self-host
deployment**. Sovereign defaults: after image pull + model cache, no runtime
network is required (set `HF_HUB_OFFLINE=1`).

## Quickstart

```sh
cp .env.example .env && source .env          # STELE_* DSNs (dedicated ports)
make up                                       # core stack (pg + mariadb + clickhouse), waits for health
cd .. && bash scripts/chunkshop-setup.sh      # one-time: cache the embedder model
make e2e                                       # run the full e2e + contract suites for real, then tear down
```

## Ports (dedicated — won't collide with other local stacks)

| Service | Host port |
|---|---|
| postgres (pgvector) | 55452 |
| mariadb | 53316 |
| clickhouse | 58133 (HTTP) / 59010 (native) |
| postgres-raggraph (Phase 5) | 55453 |

## Profiles

| Profile | Services | Use |
|---|---|---|
| `core` | postgres(pgvector), mariadb, clickhouse | Phase 1–4 full e2e (default) |
| `graph` | postgres-raggraph | Phase 5 living-knowledge (not built yet) |
| `all` | everything | CI full sweep |

## What `make e2e` proves

`tests/e2e/test_full_journey.py` walks the public Stele API
(store → index → vector/hybrid search → fetch → recall) on **all five
backends**, including mariadb + clickhouse for real. recall is asserted only
on backends with an implemented memory store (memory/sqlite/postgres);
MariaDB/ClickHouse expose artifact + vector/hybrid (their real surface).
Evidence is written to `../tests/e2e/evidence/<date>/E2E-Report.txt`.

## ClickHouse note

ClickHouse's `vector_similarity` (HNSW) index is **upstream-experimental in
all ClickHouse versions**. The harness enables it via
`clickhouse/users.d/allow-vector-index.xml`
(`allow_experimental_vector_similarity_index=1`) — the actual supported
mechanism (ClickHouse Cloud enables it by default). A self-host deployment
using ClickHouse vector retrieval must do the same.

## Targets

`make up | up-all | down | nuke | logs | dry-run | e2e | e2e-graph`

## Notes

- This does not replace the fast unit loop: `e2e` tests are deselected from
  default `pytest` (`-m 'not e2e'`); CI opts in.
- `make nuke` removes volumes for a clean slate.
- Phase 5 (`graph` profile) is reserved; see `images/postgres-raggraph/`.

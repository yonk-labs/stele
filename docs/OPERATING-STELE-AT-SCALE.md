# Operating Stele at Scale (hundreds of users)

Known issues + best practices for running Stele beyond a single local
instance. **Honest framing up front:** Stele is designed *local-first /
sovereign* (no built-in auth, one connection per instance, create-on-first-use
schema). Scaling to hundreds of concurrent users is **possible but requires
operational discipline** — it is not turn-key. Every claim below is grounded
in code (file:line); items the code does not make obviously-safe are flagged
**UNVERIFIED**, not glossed.

**Companion docs (cross-referenced, not duplicated):**
`EMBEDDING-DEPLOYMENT-GAP.md` / `EMBEDDING-FIX-PLAN.md` /
`RUNNING-STELE-AS-A-SERVICE.md` (embedding tier + service topology);
`RUNBOOK-graphrag-sweep.md §9` (answer-quality caveats).
**Ownership:** the *fixes* belong to the `phase6-7`/`main` Stele lineage;
this is an ops assessment, no code changed.

---

## Tier 1 — Hard blockers (resolve before hundreds of users)

### 1.1 No connection pooling — one DB connection per `Stele` instance
`PostgresStorageBackend` opens a single `psycopg.connect(... autocommit=True)`
per instance (`src/stele/storage/postgres.py:32`); sqlite/mariadb/clickhouse
follow the same one-connection-per-instance pattern. There is **no pool**.
- *At scale:* 100 workers → 100 Postgres connections; default
  `max_connections=100` is exhausted, plus ~10 MB/conn. SQLite is **single
  writer** (WAL, `sqlite.py:25`) — concurrent writers serialize, not viable.
- *Best practice:* **Postgres only** for scale; put **pgbouncer**
  (transaction pooling) in front; **one `Stele` instance per process**, reused
  across that process's requests (not per-request); size pool ≥ worker count.

### 1.2 Graph path deadlocks inside async frameworks
The Revisor bridges async→sync with `asyncio.run(coro)` **per call**
(`src/stele/revisor/pg_raggraph_revisor.py:74-75`, used by
`ingest_evidence`/`supersede`/`retract`/`search_current`/`search_as_of`).
`asyncio.run()` raises `RuntimeError` if called from a running event loop.
- *At scale:* any ASGI service (FastAPI/Starlette) or async agent runtime
  **cannot call the graph path directly** — hard failure, not slow. Also a
  fresh event loop per call is throughput-poor.
- *Best practice:* run graph calls in a **dedicated sync thread/worker pool**
  (`run_in_executor`), never on the event loop; or keep graph retrieval on a
  separate sync service. Keyword/vector paths are unaffected.

### 1.3 No automated retention — unbounded growth
`cleanup_expired()` is **manual** (`stash.py:472`); artifacts without
`ttl_seconds` live forever; superseded memories are **status-flagged, never
deleted** (`memory_store/sqlite.py:173-178` — a memory superseded N times
keeps N+1 rows); deleting an artifact does **not** cascade-delete pg-raggraph
graph nodes (orphans accumulate).
- *At scale:* months × hundreds of users → store/index/graph bloat → query
  slowdown and disk pressure.
- *Best practice:* schedule `cleanup_expired()` (nightly); add a job to prune
  `status='superseded'` memories; monitor artifact/chunk/graph table sizes;
  set `ttl_seconds` on ephemeral artifacts at `store()` time.

---

## Tier 2 — Major design constraints (must configure correctly)

### 2.1 Multi-tenant isolation is caller-discipline, not enforced
`MemoryScope.namespace` is a plain filter field (`core/memory_record.py:39`),
correctly parameterized (no SQL injection found) but **not cryptographically
scoped**. Two tenants both using `"default"` share data. No per-tenant auth
(by design — sovereign/local-first).
- *Best practice:* **one `Stele` instance (and ideally one DB/schema) per
  tenant** for strong isolation; or a centralized namespace registry that
  guarantees per-tenant-unique namespaces + application-layer authz on every
  call. Never let untrusted callers choose raw namespace strings.

### 2.2 Reference signing is OFF by default — forgeable refs
`SigningConfig` defaults to `mode="disabled"` (`core/config.py:92-95`);
`disabled` accepts any `stele://` reference unvalidated
(`core/reference_auth.py:42-43`). A user can craft a reference and
read/delete another's artifact. Secret is **global**, not per-tenant.
- *Best practice:* production **must** set `signing.mode="required"` with a
  strong secret. Treat the secret as a global key (leak = all tenants); plan
  rotation (note: no env override — secret is config, rotation needs reload).

### 2.3 PII scrubbing has unscrubbed surfaces
Scrubbed: stored summary, `fetch()` (when `raw=False`), search/query hits,
`Memory.add` text. **Unscrubbed:** raw artifact `content` in the backend;
`fetch(raw=True)` when `pii.raw_fetch_enabled=True` (**default False** —
`core/config.py:31`, keep it false); `export_jsonl()` exports raw records
(`stash.py:475-485`); chunk index + pg-raggraph tables store whatever was
ingested (summary-level scrub does not protect backing indexes).
- *Best practice:* keep `raw_fetch_enabled=False`; treat `export_jsonl`
  output + chunk/graph tables + DB backups as **containing raw PII** — encrypt
  at rest, restrict access, never ship exports off-box without review.

### 2.4 Embedding tier (cross-ref)
Per-instance local ONNX model load; no shared-deployment surface. Full detail
+ fix plan in `EMBEDDING-DEPLOYMENT-GAP.md` / `EMBEDDING-FIX-PLAN.md`. For
scale: set `FASTEMBED_CACHE_PATH` to a shared volume; size CPU/RAM for
per-worker model loads until WS1–WS3 land; **pin the embedding model** —
changing it requires a full reindex (output dim must match the index).

---

## Tier 3 — Operational planning (plan capacity & process)

- **Backend choice:** Postgres for scale. SQLite = dev/small only
  (single-writer). MariaDB FULLTEXT is boolean/`ft_min_word_len`-sensitive
  (short queries miss — `storage/mariadb.py:66`). ClickHouse `cleanup_expired`
  uses async **mutations** that can block queries (`clickhouse.py:179-204`) —
  schedule off-peak.
- **Schema/migrations:** **none** — create-on-first-use
  (`CREATE TABLE IF NOT EXISTS`, ad-hoc `ALTER` e.g. `sqlite.py:69-72`). No
  version system. Upgrades = hand-written migration + staging test;
  `pg-raggraph==0.3.0a3` is pinned-exact (alpha) and `chunkshop>=0.4.3,<0.5` —
  treat dependency bumps as reindex/migration events.
- **Resource/DoS:** interception loads the full output into memory before
  stashing — no size cap (`interception/thresholds.py`); a multi-hundred-MB
  tool result can OOM the worker. `stash.list()` has no max-limit cap;
  `export_jsonl` defaults `limit=100_000`. Put hard caps + per-process
  memory/timeout limits in front of any untrusted caller.
- **Concurrent-write correctness — UNVERIFIED:** two concurrent
  `Memory.add(supersedes=[id])` on the same target — the race window /
  last-writer-wins semantics are **not verified in code**; no explicit
  lock/CC documented. `as_of` reads are fine; concurrent supersession is an
  open risk — serialize writes per logical memory if correctness matters, and
  load-test this path before trusting it.
- **Answer-quality limitations (cross-ref):** the structural recall gap, the
  LoCoMo verbatim-span scorer artifact, the none/lede_spacy graph "phantom",
  and the missing memory primitives (episode segmentation / consolidation /
  bi-temporal) are documented in `RUNBOOK-graphrag-sweep.md §9` and the sweep
  report. Operationally: **don't trust raw LoCoMo-style answer-span as a
  health metric**; the trustworthy quality signal is the LLM-judged
  LME/MHR run, and graph quality is a known structural gap, not a tuning knob.

---

## Production checklist

**Mandatory before hundreds of users:**
- [ ] Postgres backend + pgbouncer (or app pool); pool ≥ worker count
- [ ] One `Stele` per process, reused; **never** call the graph path on an
      async event loop (thread-pool it)
- [ ] `signing.mode="required"` + strong, rotation-planned secret
- [ ] `pii.raw_fetch_enabled=False`; treat exports/backups/indexes as raw PII
- [ ] Scheduled `cleanup_expired()` + superseded-memory purge job
- [ ] Distinct namespace **and** app-layer authz per tenant (or instance/DB
      per tenant)
- [ ] Hard caps on `list()`/`export_jsonl()`/interception input size; process
      memory + timeout limits
- [ ] `FASTEMBED_CACHE_PATH` on a shared volume; embedding model pinned

**Recommended:**
- [ ] Load-test the concurrent-supersession path (UNVERIFIED) before trusting
- [ ] Staging-test every schema/dependency upgrade; plan reindex downtime
- [ ] Monitor: Postgres pool saturation, store/index/graph growth, p50/p95
      (watch for seconds-scale embedding init = regressed to per-instance
      loads), interception memory spikes
- [ ] Readiness probe = `run-full-sweep.sh preflight`-style checks (DB +
      embedding + LLM reachable)

## Retention & connection pooling (operations)

This expands Tier-1 §1.1 (pooling) and §1.3 (retention) with the concrete
operator surface. Read those first for the *why*; this is the *how*.

### `Stele.cleanup(...)` — the umbrella retention entrypoint

`Stele.cleanup(*, expired_artifact_limit=1000, superseded_memory_before=None)`
returns a `CleanupReport(artifacts_expired, superseded_memories_purged)`.

- It **always** runs the existing expired-artifact cleanup (same effect as
  `cleanup_expired()`, which is unchanged and still supported for back-compat).
- The superseded-memory purge is **opt-in and horizon-bounded**:
  - `superseded_memory_before=None` (**default**) → purges **zero** superseded
    memories. This is deliberately default-safe.
  - a `datetime` → hard-deletes **only** memory rows with
    `status='superseded'` **and** `effective_until` strictly before that
    cutoff. Active, still-valid, and superseded-but-recent records are kept.

**The `as_of` trade-off (by design).** `as_of` time-travel recall *reads*
superseded records — they **are** the history. Purging past a horizon
permanently forfeits time-travel for anything *before* that horizon; recent
history (anything superseded at/after the cutoff) is preserved. Choose the
horizon as your retention SLA (e.g. "keep 90 days of history"):
`superseded_memory_before = now - timedelta(days=90)`.

**Why no aggressive/auto default ships:** an automatic blanket
"delete superseded" would silently break `as_of` history for every operator
who didn't realize it ran — so operators must opt in with an explicit horizon.

### Recommended scheduled job

Run a small script from cron or a systemd timer (nightly is typical). It opens
one `Stele`, calls `cleanup()` with an explicit horizon, and exits:

```python
# retention_job.py
from datetime import UTC, datetime, timedelta
from stele import Stele

RETENTION = timedelta(days=90)  # your history-retention SLA

def main() -> None:
    stele = Stele.from_config({"backend": {"type": "postgres",
                                            "dsn": "YOUR_DSN_HERE"}})
    try:
        report = stele.cleanup(
            superseded_memory_before=datetime.now(UTC) - RETENTION,
        )
        print(report.model_dump_json())
    finally:
        stele.close()

if __name__ == "__main__":
    main()
```

```cron
# nightly at 03:17
17 3 * * *  /path/to/.venv/bin/python /path/to/retention_job.py >> /var/log/stele-retention.log 2>&1
```

(systemd-timer equivalent: a `OnCalendar=*-*-* 03:17:00` timer driving a
oneshot service that runs the same command.) This satisfies the
"Scheduled `cleanup_expired()` + superseded-memory purge job" checklist item.

### Connection pooling is still NOT built in

An internal connection pool is **deliberately not implemented** (it's a
re-architecture, tracked separately). Stele keeps one DB connection per
instance — see [Tier-1 §1.1](#11-no-connection-pooling--one-db-connection-per-stele-instance):
use **pgbouncer** (transaction pooling) or an application-level pool, one
`Stele` per process reused across requests, pool sized ≥ worker count. The
retention job above is a short-lived single-connection process, so it does not
add to steady-state pool pressure.

## Honest unknowns (not yet verified — do not assume safe)
- Thread-safety of a `Stele` instance shared across threads (per-instance
  connection reuse) — **UNVERIFIED**; assume one-per-thread or lock-wrap.
- Concurrent `supersedes` race semantics — **UNVERIFIED**.
- pg-raggraph graph-orphan accumulation after artifact delete — observed gap,
  cleanup behavior **UNVERIFIED**.
- Real per-cell embedding-init vs work split — assumption, not measured
  (`EMBEDDING-FIX-PLAN.md` WS4 is the measurement task).

## Bottom line
The codebase is sound but built for sovereign local instances, not multi-user
cloud. Hundreds of users is achievable on Postgres with: connection pooling,
graph-off-the-event-loop, signing required, retention automation, per-tenant
isolation discipline, and capacity planning for per-instance embedders until
the embedding fix lands. The Tier-1 items are genuine blockers, not polish —
treat the mandatory checklist as a gate, and surface the fix-owning items to
the `phase6-7`/`main` Stele lineage.

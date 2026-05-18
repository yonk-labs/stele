# Living Knowledge Setup (Phase 5)

Stele's Phase 5 adds **living knowledge**: a `pg-raggraph`-backed `Revisor`
that projects memory evolution into a graph so `graph_search` can honor
supersession, retraction, version families, and time-travel — while every
hit still recovers its exact `stele://` source. Like Phase 4 it is
**batteries-included**: you only ever set Stele config. `pg-raggraph`'s
`PGRGConfig` (dsn, embedding provider, evolution tier, behaviors) is
synthesized internally; the DSN is reused from your Postgres artifact
backend; Stele never mutates `os.environ`.

It is **opt-in and off by default**. Memory truth (Phase 1 evolution
columns + `supersedes=` + `as_of`) works everywhere with no graph; the
graph is a *projection*, never the source of truth.

## One-time setup

```bash
uv sync --extra all-backends --extra dev --extra chunkshop --extra postgres-graph
# or: pip install 'stele-core[postgres-graph]'
```

`[postgres-graph]` is independent of `[postgres]`. It pins the exact
`pg-raggraph` version carrying the consumer surface Phase 5 requires
(opaque caller-metadata + evolution status on results; post-hoc
`retract()`/`supersede()`; stable chunk ids). `pg-raggraph` brings its own
`psycopg`/`pgvector`. The Postgres database needs the `vector` and
`pg_trgm` extensions (the bundled harness image
`deploy/images/postgres-raggraph/` seeds both; `make -C deploy e2e-graph`
brings the whole thing up on port 55453).

## Enabling it

```python
from stele import Stele

stele = Stele.from_config({
    "backend": {"type": "postgres", "dsn": "postgresql://yonk:yonk@localhost:55453/stele"},
    "graph": {
        "enabled": True,
        "namespace": "kb",
        "evolution_tier": "structural",        # structural | fact_aware | full
        "retracted_behavior": "surface_both",  # hide | flag | surface_both
        "supersession_behavior": "prefer_new", # hide | prefer_new | surface_both
    },
})
```

* `graph.enabled=false` (default) — no projection; `graph_search` raises
  `CapabilityError`. Everything else is unaffected.
* `graph.enabled=true` but **not** a Postgres backend, or the extra absent —
  capability honesty: the `Revisor` is inert / construction fails loudly;
  memory evolution still works; `graph_search` still `CapabilityError`s.
* Only Stele config is ever set. No `pg-raggraph` YAML, no env vars.

## What gets projected

| Stele operation | Revisor projection |
| --- | --- |
| `memory.add(...)` | `ingest_evidence` — node keyed `stele://<ns>/mem-<id>`, with the memory's `effective_from` |
| `memory.add(supersedes=[old])` | `supersede(old_ref, new_ref)` — `as_of`-aware |
| `memory.retract(id, ...)` | `retract(stele_ref)` — sets status, projects retraction |
| `stele.store(...)` | `ingest_evidence` of the PII-scrubbed artifact summary |

## Querying

```python
stele.recall(query="...", scope=scope, strategy="graph_search",
             as_of=None, version_filter=None, retracted_behavior=None)
```

All three are optional and default to preserving prior behavior.

## Semantics that bite (proven against real pg-raggraph)

- **`as_of` needs an `effective_from`.** `memory.add` stamps
  `effective_from=now()`, so `as_of` *before* a memory was added excludes it;
  the recoverable historical window for a superseded memory is *between* its
  add and the superseding add. Naive (tz-unaware) datetimes are rejected with
  a `ValidationError` *before* any backend call.
- **`retracted_behavior="hide"` is absolute** — a retracted memory disappears
  from current *and* `as_of` history ("unsay it entirely").
- **`flag` / `surface_both` keep the hit and mark it** (`retracted=True`) —
  the only modes that still *cite* a retracted source historically. Stele's
  default leans `surface_both` because the product invariant is "always cite
  the evidence"; choose `hide` for right-to-be-forgotten erasure.
- **`supersede()` is `as_of`-aware**: the old version stays recoverable for
  `as_of` before the supersession; `supersession_behavior` decides the
  current view.

## Verifying

```bash
make -C deploy e2e-graph     # the Living Knowledge Verification Bar, for real
STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele \
  scripts/demo-living-knowledge.sh
```

SC→test coverage:
`docs/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md`.
Design + ground truth:
`docs/superpowers/specs/2026-05-17-phase5-pg-raggraph-living-knowledge-CORRECTED-design.md`,
`…-phase5-recon-correction-sheet.md`,
`…-phase5-task0-pg-raggraph-api-recon.md`.

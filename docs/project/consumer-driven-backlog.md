# Consumer-driven backlog (bento/Memex gap map)

Status: living. Last mapped 2026-06-26.

stele's near-term direction is set by what a real downstream consumer actually
pulls, not by self-authored benchmarks (see the `## Direction decision` block in
[current-status.md](current-status.md)). The one real consumer today is **bento**
(the Memex product on its `stele-shim` service). This doc maps what bento uses,
what it ignores, and the unmet needs that form the build queue.

## Is stele live in bento? Yes.

bento runs stele for real, not aspirationally:

- `stele-core` is vendored at `bento/backend/tools/stele/` and wired as an editable
  path dependency: `bento/backend/services/stele-shim/pyproject.toml:18`.
- The `stele-shim` FastAPI service is an active container:
  `bento/backend/docker/docker-compose.yml:40-79`.
- The BFF deliberately does NOT bundle stele-core; it calls the shim over HTTP
  (`bento/backend/api/Dockerfile:19-23`, "stele-core ... NOT installed into this
  image ... talks over HTTP via their shim services"). That is a deployment
  boundary, not stele being absent.

## What bento depends on (the real pull)

All memory-side. The shim (`bento/backend/services/stele-shim/src/stele_shim/main.py`)
exposes and bento consumes:

| stele surface | bento usage | evidence |
| --- | --- | --- |
| `store` / `fetch` / `store_many` | artifacts read + write | `routes/artifacts.py:86`, ingest |
| `memory.add` / `add_many` / `retract` / `list` / `search` | fact/preference/decision CRUD | `routes/memories.py:32-92`, `me_kbs_ingest.py:217` |
| supersession (`add(supersedes=)`, `purge_superseded`) | evolving facts | `ingredients/distiller.py:172-183`, `me_kbs_memory_consolidate.py` |
| `recall` (memory_search/artifact_search/summary_only/adaptive/raw_fetch/abstain/digest) | retrieval dispatch | `routes/recall.py:103-133` |
| `extract.from_session` (LLM) | session distillation | `ingredients/distill_runner.py` |
| `distill.rules` | rules view (only) | `routes/rules.py:42-49` |

## What bento ignores (zero pull)

These stele surfaces have no bento call sites. They are candidates to stop
investing in until a consumer need appears:

- **code-graph / `read_bounded` / codeview / codeintel** — zero references in bento.
  This is the strongest evidence for the codeintel freeze: the real consumer never
  asked for it.
- `graph_search` — intentionally disabled in the shim (`main.py:458`); pg-raggraph
  owns graph retrieval there.
- `distill.spans` (needs an embedder the shim does not wire), `distill` facts/
  precedents/state/skills/best_practices/episodes/timeline (wired, never called).
- `extract.from_messages` (bento uses chunkshop lede triples instead).
- `export_namespace` / `import_namespace`, multi-tenant schema isolation,
  artifact-layer content-hash dedup (bento works around with a bloom filter).

## The backlog (demand minus supply, ordered by real pull)

Each item is glue bento maintains *around* stele that stele could own. These are
conveniences and consolidations, not blockers (bento treats the shim as a stable
black box), but every one has a named call site, which is what makes them better
than benchmark-chosen work.

1. **`Memory.find_precedent` — SHIPPED 2026-06-26.** See adoption note below.
2. **Current-state read-model for a scope.** The deepest signal: bento writes facts
   to stele AND projects each into a separate `admin.agent_memory` SQL table, because
   `/v1/ask` needs a fast "active facts for this scope" read and stele's bi-temporal
   recall was not the right shape for that hot path
   (`bento/backend/api/ingredients/distiller.py:203-249`). A real consumer duplicated
   stele's data to work around a missing read-model. This is the one place bento found
   stele genuinely insufficient. Design candidate: a materialized current-state view so
   bento can drop the parallel table.
3. **Provenance/span linkage in `extract`.** bento manually stashes each turn as an
   artifact and threads the `stele://` ref as `source_refs`
   (`distiller.py:145-150`). stele's "every memory cites evidence" invariant could own
   the span->source bookkeeping.
4. **LLM-provider abstraction for `extract.from_session`.** The shim builds the LLM
   callable from env (`main.py:1310-1373`); stele could accept a provider abstraction so
   custom endpoints/models are configurable without shim changes.
5. Lower tier: cross-pod bulk idempotency (bento #128, per-process LRU today),
   artifact-layer content-hash dedup, surfacing the artifact summary the shim leaves
   blank (`routes/artifacts.py:690`).

## Adoption note: `Memory.find_precedent` (item 1)

bento's distiller currently hand-rolls the supersession-candidate lookup: list all
active facts in the namespace, then filter by matching `(subject, predicate)` metadata
(`bento/backend/api/ingredients/distiller.py:153-183`). stele now owns that:

```python
# Before (bento distiller, ~15 lines of glue):
#   lr = await client.get(f"{shim_url}/v1/memories", params={"namespace": ns, "limit": 1000})
#   existing = [m for m in lr.json()["memories"] if m["kind"] == "fact" and m["status"] in (None, "active")]
#   supersedes = [m["memory_id"] for m in existing
#                 if _meta_triple(m)["subject"] == content["subject"]
#                 and _meta_triple(m)["predicate"] == content["predicate"]]

# After (stele owns it):
precedents = stele.memory.find_precedent(
    scope,
    match={"subject": content["subject"], "predicate": content["predicate"]},
    kind="fact",
)
supersedes = [p.id for p in precedents]
```

`find_precedent(scope, *, match, kind=None, limit=1000)` returns the active records in
`scope` whose `metadata` contains all `match` pairs. Active-only (superseded records are
never precedents), contract-tested on memory/sqlite/postgres. To use it over the shim,
the shim adds a thin `find_precedent` passthrough endpoint and bento's distiller calls it
instead of the list+filter. Note: it is a Python facade method today (library-first, like
the lifecycle tools); MCP/CLI exposure is a tracked follow-up.

## How this list is maintained

Re-map when bento's stele usage changes materially. The map is built by reading
bento's actual call sites, not its roadmap: what it calls, what it works around,
and what it never touches.

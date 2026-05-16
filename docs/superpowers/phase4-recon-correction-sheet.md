# Phase 4 — Recon Correction Sheet (GROUND TRUTH)

**Status:** Authoritative. The original Phase 4 plan/spec
(`plans/2026-05-14-phase4-chunkshop-indexing.md`) were AI-authored against
*assumed* APIs and are **fiction** wherever they conflict with this file.
This sheet was produced by reading the real installed `chunkshop` source and
the real shipped `stele` code, then re-verified against PyPI `chunkshop==0.4.2`.

**chunkshop version note:** Verified against 0.4.1 (git) and 0.4.2 (PyPI) —
Python API byte-identical. **0.4.3 (2026-05-16) is additive + backward
compatible** and changes two things in our favour (see §0). Re-verify with the
new-session Task 0, but the surface below holds.

---

## §0 — chunkshop 0.4.3 deltas (USE THESE)

0.4.3 is additive and backward-compatible. Two changes directly relevant:

1. **Direct `dsn` field on `TargetConfig` (and `*_table` sources).** Accepts a
   literal connection string OR `${VAR}` references expanded from the
   environment at connect time. **Takes precedence over `dsn_env`.** If `dsn`
   is unset, the legacy `os.environ[dsn_env]` path is used unchanged.
   → **The Stele ChunkStore wrappers MUST use `TargetConfig(..., dsn=<conn>)`
   directly. Do NOT mutate `os.environ`.** This obsoletes the
   "biggest gotcha" in §1 (the `os.environ[dsn_env]` dance). Prefer a literal
   path for the local sqlite file; prefer `${VAR}` or `dsn_env` for
   credentialed DSNs so secrets don't land in a config object/file.
2. **`chunkshop prefetch --config X` CLI.** Downloads the embedder model named
   in a config up front. Honors `HF_HUB_OFFLINE=1` (fail fast when uncached).
   → **This is the batteries-included setup primitive.** The Stele setup
   script calls `chunkshop prefetch` (or the equivalent fastembed download)
   so the multi-second ONNX fetch happens at install/CI time, never silently
   inside `Stele.store()`.

`bakeoff` config in chunkshop is unchanged (still `dsn_env`-only by design) —
irrelevant to us; Stele consumes bakeoff *result files*, not chunkshop bakeoff.

---

## §1 — chunkshop real API

**There is NO** `chunkshop.sqlite`, `SQLiteRetrievalIndex`,
`.index(doc_id=,text=,metadata=)`, `.keyword_search()`, `.vector_search()`,
or row objects with `.metadata/.ordinal/.score/.text`. All fiction.

### Version
```python
import importlib.metadata
importlib.metadata.version("chunkshop")   # "0.4.2"/"0.4.3" — chunkshop.__version__ does NOT exist
```

### Public surface
`from chunkshop import Pipeline, CellConfig, load_config` — the only top-level
exports. Sinks/backends/embedders/chunkers are loaded from config.

### Pipeline (chunkshop/pipeline.py)
```python
class Pipeline:
    def __init__(self, cfg: CellConfig) -> None: ...      # cfg.source must be InlineSource; calls sink.create_table()
    @classmethod
    def from_yaml(cls, path) -> "Pipeline": ...
    def ingest_text(self, doc_id: str, text: str, metadata: dict|None=None, title: str|None=None) -> int
    def ingest_document(self, doc: Document) -> int
    def delete_document(self, doc_id: str) -> int
    def count_docs(self) -> int
```
**`Pipeline` has no query method.** Vector search lives on the `Sink`
(`pipeline._sink`, private). Recommended: build sink + embedder + chunker
explicitly (below), don't drive through Pipeline.

### Sink protocol (chunkshop/sinks/base.py) — the real read/write surface
```python
class Sink(Protocol):
    def create_table(self) -> None: ...
    def write_document(self, doc_id: str, chunks: list[Chunk],
                        embeddings: np.ndarray,
                        tags_per_chunk: list[list[str]]) -> None: ...
    def delete_document(self, doc_id: str) -> int: ...
    def count_docs(self) -> int: ...
    def query_top_k(self, query_vec: np.ndarray, k: int
                     ) -> list[tuple[str, int, float]]: ...   # [(doc_id, seq_num, distance_ascending)]
```
All four sinks (`SqliteSink, PgSink, MariaDbSink, ClickHouseSink` under
`chunkshop.sinks.{sqlite,pg,mariadb,clickhouse}`) implement this identically.

### Construction
```python
from chunkshop.sinks import load_sink        # load_sink(cfg: TargetConfig, embed_dim: int) -> Sink
from chunkshop.backends import load_backend
from chunkshop.embedders import load_embedder
from chunkshop.chunkers import load_chunker
```
`load_sink` switches on `cfg.type ∈ {"postgres","sqlite","mariadb","clickhouse"}`,
internally calls `load_backend`, returns the matching `*Sink`. **Verify
`load_sink`/`load_backend` real signatures by reading
`chunkshop/sinks/__init__.py`, `chunkshop/backends/__init__.py` before use.**

### TargetConfig (chunkshop/config.py, extra="forbid")
```python
TargetConfig(
    type="sqlite"|"postgres"|"mariadb"|"clickhouse",
    dsn=<literal conn string or "${VAR}">,     # 0.4.3+; PREFER THIS, no os.environ
    # dsn_env=<env var NAME>,                  # legacy fallback only
    database=<name ^[a-z_][a-z0-9_]*$>,        # alias; attr is database_name
    table=<name ^[a-z_][a-z0-9_]*$>,
    hnsw=True, mode="overwrite"|"append"|"create_if_missing",
    source_tag=None,
)
```

### Embedder (chunkshop/embedders/base.py)
```python
class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> np.ndarray: ...   # (N, dim)
```
`from chunkshop.config import FastembedEmbedder` →
`FastembedEmbedder(type="fastembed", model_name="sentence-transformers/all-MiniLM-L6-v2", dim=384)`
→ `load_embedder(cfg)`. Dim auto-detect: `embedder.embed(["__stele_probe__"]).shape[1]`.
**fastembed downloads ONNX from HF on first use** (~/.cache/fastembed). NOT
offline-safe by default → use `chunkshop prefetch` in setup; gate
chunkshop-backed tests on model availability, not just `find_spec`. The model
`all-MiniLM-L6-v2` (dim 384) is currently cached in this worktree.

### Chunker
`load_chunker(cfg)`; `chunker.chunk(Document) -> list[Chunk]`.
`Document(id, content, title=None, metadata=None)` (frozen dc, chunkshop.sources.base).
`Chunk(doc_id, seq_num, original_content, embedded_content, metadata)` (frozen dc).
`FixedOverlapChunker` cfg: `window_words` (300), `step_words` (150) — NOT
`overlap_words`. **`src/stele/indexing/chunk_index.py::_try_chunkshop_chunks`
already builds chunks correctly — reuse that exact pattern.**

### Hard consequences for Tasks 14–17
- **chunkshop is VECTOR-ONLY.** No keyword search. `keyword_search` on
  chunkshop-backed stores = Stele-local (`from stele.retrieval.rank import
  keyword_score, snippet_around`) over locally-retained chunk text.
- **`query_top_k` returns `(doc_id, seq_num, distance)` only** — no text, no
  metadata, no similarity. The ChunkStore MUST retain `{f"{doc_id}:{seq}":
  (text, reference, metadata)}` at write time to hydrate `SearchHit.text`;
  derive `SearchHit.score` from distance (cosine → `clamp(1.0 - distance, 0, 1)`).
- **No one-call `index()`**: `write` = chunk → `embedder.embed([c.original_content...])`
  → `sink.write_document(doc_id, chunks, embeddings_ndarray, [[] for _ in chunks])`.
- Query vector from the SAME embedder; `sink.query_top_k(qvec, k)`.
- Delete is `sink.delete_document(doc_id)` — by doc_id only; no delete-by-ref.
- **0.4.3:** pass `TargetConfig(dsn=<path-or-DSN>)`; do NOT touch `os.environ`.

### Recommended Stele-side ChunkStore architecture
Each chunkshop-backed `ChunkStore` owns: one `Embedder` (load_embedder), one
chunker (load_chunker), one `Sink` (load_sink, built with `TargetConfig(dsn=…)`),
plus `dict[chunk_id -> (text, reference, metadata)]`. `doc_id` = Stele
`artifact_id`; chunk id = `f"{artifact_id}:{seq_num}"` (matches `stele_chunk_id`
and `ChunkRecord.chunk_id`). **All chunkshop config synthesized internally from
Stele's `IndexingConfig` — users never see chunkshop config or env vars.**

---

## §2 — Stele core API reality (paths under the worktree root)

- `Stele.__init__(self, config: StashConfig)` — positional. `Stele(StashConfig())`
  and `Stele(StashConfig.load({...}))` both work. `Stele.from_config(...)` also exists.
- `Stele.store(content: str|bytes, *, namespace="default", session_id=None,
  content_type=None, metadata=None, lifecycle="manual", ttl_seconds=None,
  index=None) -> StoredResult`. **First param is `content`, positional — NOT
  `data=`.** Every plan `store(data=...)` is wrong → `store("text", namespace="default")`.
  `StoredResult` has `.artifact_id, .reference, .index_status` (+more).
- `Stele.search(reference: str, query: str, *, limit=10, mode=None, raw=False)
  -> list[SearchHit]` and `Stele.query(namespace: str, query: str, *, limit=10,
  mode=None, session_id=None, filters=None, raw=False)`. **LOCKED Phase-1
  signatures. Task 21 must NOT make `reference` optional or reorder.** Add
  vector/hybrid as internal branches on `effective_mode = mode or
  self.config.retrieval.default_mode`; keep existing keyword + chunk_index
  paths. `query()` is already the global API — do not add a `search(query=)` overload.
- `Stele.fetch(reference: str, *, raw=False, scrub=None) -> FetchResult`. Takes
  a **reference**, not artifact_id. `FetchResult` has **no `.record`**. For an
  `ArtifactRecord` (async re-index worker): `self.storage.fetch(
  validate_reference_signature(task.reference, self.config.signing))`.
- `Artifact`/`ArtifactRecord` required: `artifact_id, reference, namespace,
  content, summary, digest_sha256, byte_size, token_estimate`. Defaulted:
  `session_id, content_encoding="utf-8", content_type="text", metadata={},
  raw_summary=None, lifecycle, created_at/updated_at`. Plan test factories
  construct fine. `artifact.content_as_text()` exists.
- `SearchHit(artifact_id, reference, chunk_id=None, text, score,
  retrieval_mode="keyword", scrubbed=True, pii=None, metadata={})`.
  `retrieval_mode` ∈ `Literal["keyword","vector","hybrid","graph"]`.
- Exceptions in `stele.core.exceptions` (all exist, exact names):
  `OptionalDependencyError, BackendError, ConfigError, CapabilityError,
  ValidationError`, etc. Plan imports correct.
- `core/types.py`: `RetrievalMode = Literal["keyword","vector","hybrid","graph"]`
  (already has vector/hybrid → **Task 1 is a no-op, already done**).
  `IndexStatus = Literal["queued","indexed","skipped","failed"]` — **has
  `"queued"`, NOT `"pending"`. Plan Task 9's IndexStatus edit is wrong; reuse
  `"queued"`** (already handled in commit fcd2260).
- `StashConfig.load(value)` classmethod exists (dict/str/Path/None/StashConfig).
- `IndexingConfig` ALREADY has Phase 4 fields + validators (commit 8b65714);
  `RetrievalConfig.default_mode: RetrievalMode = "keyword"`. **Tasks 2,3,4 done.**
- `bakeoff.py` exists (`BakeoffEmbedder/Chunker/Config/Summary`,
  `load_bakeoff_file`). Verify `overlay_onto_indexing_config` exists before
  Task 22 (add if missing).
- **`Stele.capabilities()` returns `StashCapabilities`** (`core/capabilities.py`),
  NOT the (now-deleted) orphan `Capabilities`. `StashCapabilities` was extended
  with the 7 Phase 4 fields in commit 91b0737 (`chunk_store_backend,
  vector_enabled, hybrid_enabled, chunkshop_installed, chunkshop_version,
  bakeoff_summary, task_backend`). Task 23 populates them on the REAL type;
  version via `importlib.metadata.version("chunkshop")`. `__init__.py` (Task 29)
  exports `StashCapabilities`, not `Capabilities`.
- `recall/artifact_search.py`: `ArtifactSearchStrategy` calls
  `deps.stele.search(fetched.reference, request.query, limit=...)` /
  `deps.stele.query(...)` with **no `mode`** → with the safe Task-21 approach
  it auto-picks `config.retrieval.default_mode`. **SC-024 needs ZERO recall
  changes** (and `recall/` must stay chunkshop/concurrency-free — arch test).

---

## §3 — Per-task corrections (11–33)

- **11 InProcessChunkStore:** plan code mostly OK (numpy hash-embed, no
  chunkshop). Verify `ChunkIndex._chunks_by_ref` private attr name. Offline-deterministic.
- **12 dim_resolution:** plan OK. `resolve_dim_and_similarity(config,*,store)`.
- **13 chunkshop_adapter:** plan OK (pure string translation, no chunkshop import).
- **14 SQLiteChunkStore / 15 Postgres / 16 MariaDB / 17 ClickHouse:** REWRITE
  per §1. Use 0.4.3 `TargetConfig(dsn=<sqlite file path> | <DSN>)`. find_spec
  guard targets `"chunkshop"`. Retain chunk text locally; vector via
  `query_top_k`; keyword Stele-local; PII regex assert on `write`; score =
  clamp(1-distance). sqlite ctor `(config, *, db_path)`; pg/mariadb/clickhouse
  ctor `(config, *, dsn)`. Tests RUN for real (model cached); only the
  `OptionalDependencyError` test is `skipif find_spec("chunkshop") is not None`.
- **18 vector.py + hybrid.py + DC-001:** plan OK. No chunkshop import in
  retrieval/ (DC-001 grep must be empty).
- **19 hybrid_quality + fixture + DC-003:** plan OK; load-bearing; ≥20 pairs;
  default floor 0.05; `STELE_HYBRID_FLOOR` env override.
- **20 SyncChunkIndexer:** real `__init__(self, index: ChunkIndex)` with
  `submit()`/`status()`/`index_now()`. PRESERVE submit/status; only swap the
  write call; branch `isinstance(self._target, ChunkIndex)`. Keep `NoOpIndexer`.
- **21 stash.py wiring (HIGH RISK):** keep locked `search`/`query` signatures;
  add internal mode dispatch (default = `config.retrieval.default_mode`); add
  `self._chunk_store` (keep existing `self.indexer` name + call sites);
  `indexing_status` returns `IndexResult`; async worker uses `task.reference` +
  `self.storage.fetch(validate_reference_signature(...))`; change indexer gate
  to build a chunk store whenever `indexing.mode != "skip"` (NOT gated on
  `provider=="chunkshop"`); extend `close()` additively (keep `self.storage.close()`).
- **22 bakeoff overlay + DC-004:** verify/implement `overlay_onto_indexing_config`;
  `self.config = self.config.model_copy(update={"indexing": ...})`.
- **23 capabilities():** populate the 7 Phase 4 fields on `StashCapabilities`
  (keep `storage=`/`retrieval=` sub-models); `chunkshop_version` via
  `importlib.metadata.version` (try/except PackageNotFoundError).
- **24 Phase 3 integration:** `store("...", namespace=)` positional; verify
  `stele.recall.artifact_search(query=,scope=,artifact_id=)` shape +
  `MemoryScope` field names.
- **25 vector contract (5 backends):** `store(...)` positional; sqlite + pg run
  for real (model cached, PG DSN set); mariadb/clickhouse gated on
  `chunkshop.sinks.{mariadb,clickhouse}` + DSN env. Unique table per run.
- **26 indexing modes contract:** `store(...)` positional; ensure Task-21 gate
  builds chunk store for sync/async (else "skipped"); align `queued` vs `pending`.
- **27 PII assertion:** memory backend `pytest.skip` (trusts upstream);
  chunkshop-backed wrappers assert + test for real.
- **28 pyproject pin:** DONE (b7d9110, 0.4.2). **New session bumps to
  `chunkshop[all-backends]>=0.4.3,<0.5`** and re-verifies API + runs prefetch.
- **29 __init__ exports:** export `StashCapabilities` (extended), `Bakeoff*`,
  `IndexTask`, `TaskStatus`. NOT `Capabilities` (deleted).
- **30 architecture test:** `parents[3]` = worktree root (correct). Adds
  `tests/unit/indexing/test_architecture.py` (no name collision).
- **31 SC→test map:** write to
  `docs/superpowers/specs/2026-05-16-phase4-chunkshop-indexing-sc-coverage.txt`
  (repo convention), NOT `/tmp`.
- **32 re-run DCs:** DC-001/002/003/004. (DC-002 already green.)
- **33 full verification + DC-FINAL:** trio + Out-of-Scope grep + locked-files
  grep (recall/ untouched proves the safe Task-21 approach held).

### Cross-cutting (inject into every implementer)
1. `store(data=)` → `store("<content>", namespace=)` positional.
2. `fetch(artifact_id)` → `fetch(reference)`; no `.record`; use `self.storage.fetch`.
3. No `chunkshop.sqlite/.postgres/...` → `chunkshop.sinks.{sqlite,pg,mariadb,clickhouse}` via loaders.
4. chunkshop vector-only; `query_top_k` bare tuples; retain text locally; keyword Stele-local.
5. **0.4.3: `TargetConfig(dsn=…)` directly — never mutate `os.environ`.**
6. `chunkshop.__version__` absent → `importlib.metadata.version("chunkshop")`.
7. Tasks 1–4 done; `IndexStatus` has `"queued"` not `"pending"`.
8. `capabilities()` → `StashCapabilities` (extended, 91b0737); orphan deleted.
9. `search`/`query` signatures LOCKED; internal mode dispatch; default =
   `config.retrieval.default_mode` (also makes SC-024 work with 0 recall changes).
10. fastembed downloads on first use; `chunkshop prefetch` in setup; gate
    chunkshop tests on model availability, not just `find_spec`.
11. Task-21 indexer gate: build chunk store when `mode != "skip"` (not on `provider`).
12. Real per-task conventional commits (`feat(scope): … (SC-xxx)`); the plan's
    `/tmp/.../PROGRESS.log` steps are dead — ignore them.

# Vector & Hybrid Indexing Setup (Phase 4)

Stele's Phase 4 adds production vector + hybrid retrieval across all five
backends via [chunkshop](https://pypi.org/project/chunkshop/). It is
**batteries-included**: you only ever set Stele's `IndexingConfig`. All
chunkshop configuration (cell, target, embedder, chunker) is synthesized
internally — there is no chunkshop YAML to write and no chunkshop
environment variable to set. Connections use chunkshop 0.4.3's
`TargetConfig(dsn=...)` directly (the DSN/path is reused from your Stele
artifact backend); Stele never mutates `os.environ`.

## One-time setup

```bash
uv sync --extra all-backends --extra dev --extra chunkshop   # or: pip install 'stele-core[chunkshop]'
scripts/chunkshop-setup.sh
```

`scripts/chunkshop-setup.sh` prefetches the fastembed embedder model
(`sentence-transformers/all-MiniLM-L6-v2`, dim 384) so the multi-second
ONNX download happens at install/CI time — never silently inside
`Stele.store()`.

## Enabling it

```python
from stele import Stele

stele = Stele.from_config({
    "backend": {"type": "sqlite", "path": ".stele/stele.db"},
    "indexing": {"mode": "sync"},          # "skip" | "sync" | "async"
    "retrieval": {"default_mode": "hybrid"},  # "keyword" | "vector" | "hybrid"
})
stele.store("the user prefers dark mode dashboards", namespace="prefs")
hits = stele.search(ref, "dark mode", mode="vector")   # or mode="hybrid"
```

* `indexing.mode="skip"` — no chunk store built; `vector` mode raises
  `CapabilityError`.
* `indexing.mode="sync"` — chunked + embedded inline before `store()` returns.
* `indexing.mode="async"` — indexed on an in-process worker thread;
  `store()` returns immediately with `index_status="queued"`; poll
  `stele.indexing_status(artifact_id)`.

## Offline behavior

Once the model is cached, set `HF_HUB_OFFLINE=1` and the embed path never
touches the network. Run `scripts/chunkshop-setup.sh` **before** going
offline (or bake it into your CI image). The in-process `memory` chunk
store uses a deterministic hash embedder and is always offline-safe with
no model download.

> fastembed's default cache is `/tmp/fastembed_cache` (not
> `~/.cache/fastembed`). Override with `FASTEMBED_CACHE_PATH` if you need
> it on a persistent volume.

## Real backends for vector tests

```bash
scripts/postgres-up.sh                                   # STELE_PG_DSN
docker compose -f docker-compose.backends.yml up -d      # MariaDB + ClickHouse
```

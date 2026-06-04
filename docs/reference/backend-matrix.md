# Backend Matrix

`stele` keeps the public contract stable while each backend uses its
own native storage and retrieval behavior.

| Backend | Exact Store | Retrieval | Delete | Notes |
| --- | --- | --- | --- | --- |
| Memory | yes | in-process keyword plus optional chunk index | immediate | test/dev and deterministic benchmarks |
| SQLite | yes | FTS5 | immediate | default durable local backend |
| Postgres | yes | `tsvector` full-text | immediate | primary production backend; pgvector/graph work can layer on later |
| MariaDB | yes | FULLTEXT with LIKE fallback | immediate | requires `stele-core[mariadb]` |
| ClickHouse | yes | lower-case text predicate scan | mutation based | requires `stele-core[clickhouse]`; hard delete is eventually consistent |

## Portable Replay

Use `Stele.export_jsonl(path)` and `Stele.import_jsonl(path)` to move
the same artifact set between backends. The stream preserves:

- artifact ID and `stele://` reference
- namespace and session ID
- exact content, including bytes
- content type and encoding
- metadata
- summaries
- lifecycle and timestamps

## Chunked Retrieval

Set:

```yaml
indexing:
  provider: chunkshop
  mode: sync
  chunk_words: 220
  chunk_overlap_words: 60
```

When Chunkshop is installed, the adapter uses its fixed-overlap chunker. Without
Chunkshop, the package keeps a deterministic fixed-overlap fallback so core tests
and local demos remain repeatable. Public search results stay package-owned
`SearchHit` objects either way.

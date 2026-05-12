# Current Status

Date: 2026-05-12

## Summary

`stele` is now a functional clean-room baseline with exact artifact
storage, PII-safe model-visible surfaces, targeted retrieval, multi-backend
contracts, Docker repeatability, and local benchmark evidence.

It is not yet claim-grade against external third-party memory/RAG benchmarks.
No external benchmark suite has been run yet.

## Implemented

- Public `Stele` facade for `store`, `fetch`, `search`, `query`, `list`,
  `delete`, `cleanup_expired`, `export_jsonl`, and `import_jsonl`.
- `stele://` references only.
- Exact artifact storage and fetch.
- PII scrubbing for summaries, fetch output, and search results.
- Raw fetch gate through `pii.raw_fetch_enabled`.
- Structural tool-result interception wrapper.
- `lede` summary provider.
- Memory backend.
- SQLite backend with FTS5 retrieval.
- Postgres backend with exact storage and full-text retrieval.
- MariaDB backend with exact storage and keyword retrieval.
- ClickHouse backend with exact storage and basic keyword retrieval.
- Chunkshop-backed chunk indexing path with deterministic fallback.
- JSONL export/import for migration and cross-backend replay.
- Docker startup scripts for repeatable backend testing.
- Fast local showcase HTML: `showcase.html`.

## Verified

Latest local checks:

- `ruff check .`: passed
- `mypy src tests benchmarks`: passed
- `pytest`: 45 passed
- Clean-room legacy-name scan: no matches

Backend verification:

- `scripts/test-backends.sh`: passed in prior run
- Memory, SQLite, Postgres, MariaDB, and ClickHouse contract tests passed
- Five-backend showcase produced 25 workload/backend rows

Long deterministic run:

- 35 scenario families
- 5 backends
- 25 repeats
- 4,375 scenario/backend executions
- 97.2107% mean payload reduction
- 1.0 exact fetch accuracy
- 1.0 deterministic answer-span retrieval accuracy
- 0 PII leaks

Answer workflow judge run:

- Local OpenAI-compatible server: `http://192.168.1.193:8000/v1`
- Model: `Intel/Qwen3-Coder-Next-int4-AutoRound`
- 35 scenarios x 5 strategies
- 175 judged runs

Observed strategy results:

| Strategy | Accuracy | Mean Tokens | LLM Trips | Search Calls | Fetch Calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| summary_only | 91.43% | 325 | 1.0 | 0.0 | 0.0 |
| summary_then_search | 91.43% | 390 | 1.46 | 0.46 | 0.0 |
| search_first | 97.14% | 166 | 1.0 | 1.0 | 0.0 |
| adaptive | 94.29% | 4,101 | 1.89 | 0.46 | 0.43 |
| raw_fetch | 94.29% | 8,974 | 1.0 | 0.0 | 1.0 |

Current local finding: `search_first` was the cheapest high-accuracy strategy on
the current scenario set. This should guide implementation, but it is not yet a
third-party benchmark result.

## Not Yet Done

External third-party benchmarks have not been run:

- LongMemEval
- LoCoMo
- RAGBench
- LongBench
- CRAG
- MultiHop-RAG

Competitor baselines have not been run:

- Mem0
- Zep / Graphiti
- Letta
- MemPalace
- Mastra Observational Memory
- Supermemory
- LangMem / LangChain memory
- CrewAI / LlamaIndex memory

Framework integrations are not complete:

- LangChain middleware
- MCP server/tools
- OpenAI Agents SDK style integration
- Runtime policy engine for adaptive retrieval selection

Vector/graph retrieval is not complete:

- Chunkshop vector sink integration
- pgvector retrieval through Chunkshop
- pg-raggraph Postgres adapter
- Hybrid rank fusion

## Benchmark Interpretation

Current benchmark evidence is real but repo-owned.

The fast showcase proves:

- backend path works
- payload replacement is large
- PII scrubbing is exercised
- exact fetch/search/list/delete contracts work

The deterministic long-run proves:

- broad local scenario coverage
- repeatability
- backend consistency
- PII and exact fetch invariants

The answer workflow benchmark is the most product-relevant local evidence. It
measures:

- whether summary alone is enough
- whether search is enough
- whether adaptive search/fetch improves quality
- whether raw fetch is worth the token cost
- estimated token cost
- LLM round trips
- search calls
- fetch calls
- judged correctness

It still needs external dataset validation before public claims.

## Next Steps

1. Add external benchmark adapters.

   Start with LongMemEval and LoCoMo because they directly test long-term memory,
   temporal recall, updates, and abstention.

2. Add RAG benchmark adapters.

   Add RAGBench, CRAG, MultiHop-RAG, and LongBench to test retrieval and
   long-context behavior beyond hand-built fixtures.

3. Make the answer workflow benchmark policy-driven.

   Implement a strategy selector that chooses among summary-only, search-first,
   summary-then-search, adaptive, and raw-fetch based on scenario features and
   measured outcomes.

4. Improve adaptive strategy.

   Current adaptive is expensive and not better than search-first on local data.
   It should only escalate when the summary/search confidence is low.

5. Add vector retrieval.

   Wire Chunkshop vector indexing and retrieval so search-first can become
   semantic search-first, not only keyword/chunk search.

6. Add Postgres excellence path.

   Keep Postgres as the strongest backend:

   - pgvector via Chunkshop
   - optional pg-raggraph adapter
   - richer hybrid search
   - Postgres-specific benchmark rows

7. Add framework integrations.

   Prioritize LangChain middleware and MCP tools so users can test the product in
   real agent loops.

8. Add public benchmark report generation.

   Generate a single report that separates:

   - fast local smoke
   - deterministic long-run
   - LLM-judged answer workflow
   - external third-party benchmarks
   - competitor baselines

## Completion Bar

The project should not be called complete until:

- external third-party benchmark adapters run end-to-end
- at least LongMemEval and one RAG benchmark have published local results
- answer workflow benchmark hits >=90% judged task accuracy with clear token and
  round-trip accounting
- PII leakage remains zero on configured PII fixtures
- all five backends pass contract tests
- Docker repeatability works from a clean checkout
- README and showcase clearly distinguish local evidence from external claims

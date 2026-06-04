# Stele Documentation

`stele` is an off-prompt memory layer for LLM agents: it intercepts large tool
outputs, stores the exact bytes behind a `stele://` reference, returns scrubbed
summaries plus bounded retrieval snippets to the model, and serves targeted
retrieval back across pluggable backends.

This is the curated index. Each entry says what you learn from it.

## Start here

- [getting-started/quickstart.md](getting-started/quickstart.md): five minutes to a working agent with stele wired in (CLI + MCP).
- [getting-started/tutorial-sovereign-memory.md](getting-started/tutorial-sovereign-memory.md): the memory loop end to end (store, extract, supersede, recall) as a runnable Python walkthrough.

## Guides

- [guides/agent-integration.md](guides/agent-integration.md): plug stele into an agent (Claude, Codex, MCP, Python SDK, hooks).
- [guides/memory-distillation-guide.md](guides/memory-distillation-guide.md): how periodic distillation reduces artifacts into durable memory, with usage and internals.
- [guides/episodic-recall-guide.md](guides/episodic-recall-guide.md): episodes, timeline, and cross-session spans, step by step with example output.
- [guides/filtered-retrieval-guide.md](guides/filtered-retrieval-guide.md): `query(filters=...)` by time, metadata, and facts, plus opt-in temporal routing for "last week" style queries.
- [guides/retrieval-tuning-guide.md](guides/retrieval-tuning-guide.md): tune a graph or hybrid setup when recall falls short.
- [guides/hybrid-search-guide.md](guides/hybrid-search-guide.md): getting keyword-plus-vector hybrid search right.
- [guides/vector-indexing-setup.md](guides/vector-indexing-setup.md): set up vector and hybrid indexing (Phase 4) with the batteries-included Chunkshop path.
- [guides/living-knowledge-setup.md](guides/living-knowledge-setup.md): superseding facts, retracting, and time-travel queries on a Postgres plus pg-raggraph stack (Phase 5).
- [guides/postgres-setup-and-tests.md](guides/postgres-setup-and-tests.md): the Postgres demo plus repeatable backend tests.

## Reference

- [reference/cli-reference.md](reference/cli-reference.md): every `stele` subcommand, flags, and troubleshooting.
- [reference/mcp-tools-reference.md](reference/mcp-tools-reference.md): canonical schema of all 18 MCP tools (each with its CLI equivalent).
- [reference/memory-types.md](reference/memory-types.md): the memory kinds, distill views, and benchmark modes, reconciled.
- [reference/backend-matrix.md](reference/backend-matrix.md): which capabilities each backend supports (memory, sqlite, postgres, mariadb, clickhouse).

## Architecture

- [architecture/architecture.md](architecture/architecture.md): the sovereign-stele architecture, subsystems, and the invariants that hold them together.

## Operations & Security

- [operations/running-as-a-service.md](operations/running-as-a-service.md): operate stele as a durable, horizontally-scaled service with a shared embedding tier.
- [operations/operating-at-scale.md](operations/operating-at-scale.md): operating stele for hundreds of users.
- [operations/SECURITY.md](operations/SECURITY.md): security posture and threat model.
- [operations/mcp-auth-model.md](operations/mcp-auth-model.md): the v1 auth model (stdio-only, local-trusted boundary) and why it is safe.

## Contributing

- [contributing/release-smoke-checklist.md](contributing/release-smoke-checklist.md): the manual smoke checklist to run before a release.

## Project status

- [project/current-status.md](project/current-status.md): what is implemented versus still missing, phase by phase.

## Specs

The authoritative product, API, and backend specs. Treat these as the source of
truth when behavior is ambiguous.

- [specs/README.md](specs/README.md): index of the build specs (product/API, backend/retrieval, testing/benchmark, execution plan, backlog).

## Benchmarks

Reproducible benchmark recipes and the written-up findings. Raw run dumps (logs,
per-case JSON) live outside `docs/` under `benchmarks/results/` so the docs tree
stays readable.

Recipes (how to reproduce a given benchmark):

- [benchmarks/recipes/README.md](benchmarks/recipes/README.md): index of the recipes.
- [benchmarks/recipes/locomo.md](benchmarks/recipes/locomo.md): LoCoMo recipe.
- [benchmarks/recipes/longbench.md](benchmarks/recipes/longbench.md): LongBench recipe.
- [benchmarks/recipes/longmemeval.md](benchmarks/recipes/longmemeval.md): LongMemEval-S recipe.
- [benchmarks/recipes/multihop-rag.md](benchmarks/recipes/multihop-rag.md): MultiHop-RAG recipe.
- [benchmarks/recipes/ragbench.md](benchmarks/recipes/ragbench.md): RAGBench recipe.
- [benchmarks/recipes/unavailable.md](benchmarks/recipes/unavailable.md): benchmarks not yet runnable, with architecture, expectations, and what unblocks them.

Findings (what the runs showed):

- [benchmarks/findings/showcase-report-2026-05-20.md](benchmarks/findings/showcase-report-2026-05-20.md): the showcase report (payload reduction, fetch correctness, latency, PII leakage).
- [benchmarks/findings/agentic-memory-comparison.md](benchmarks/findings/agentic-memory-comparison.md): the agentic-memory landscape and an honest cross-system comparison.
- [benchmarks/findings/memory-modes-results-2026-06-02.md](benchmarks/findings/memory-modes-results-2026-06-02.md): consolidated results across the six memory modes.
- [benchmarks/findings/session-distillation-results-2026-06-03.md](benchmarks/findings/session-distillation-results-2026-06-03.md): distillation tested on real agent transcripts.
- [benchmarks/findings/retrieval-investigation-log.md](benchmarks/findings/retrieval-investigation-log.md): the retrieval investigation log.
- [benchmarks/findings/lane-metrics-ledger.md](benchmarks/findings/lane-metrics-ledger.md): ledger of chunker, packing, and filter experiments.
- [benchmarks/findings/judge-reliability-findings.md](benchmarks/findings/judge-reliability-findings.md): judge reliability and the abstention-crediting discovery.
- [benchmarks/findings/model-matrix-findings.md](benchmarks/findings/model-matrix-findings.md): model-matrix findings and honest caveats.
- [benchmarks/findings/model-matrix-2026-05-27.md](benchmarks/findings/model-matrix-2026-05-27.md): the model matrix (Mem0 versus stele across answerers, judge held constant).
- [benchmarks/findings/why-newer-models-score-higher.md](benchmarks/findings/why-newer-models-score-higher.md): why newer models score higher on the same retrieved context.
- [benchmarks/findings/consolidation-chunker-bake-2026-05-28.md](benchmarks/findings/consolidation-chunker-bake-2026-05-28.md): the consolidation-chunker bake (n=30 LoCoMo).
- [benchmarks/findings/consolidation-chunker-deep-2026-05-28.md](benchmarks/findings/consolidation-chunker-deep-2026-05-28.md): the deeper consolidation-chunker test (n=100 LoCoMo, production-plumbed).

## Archive

Historical planning docs, superseded designs, and one-off assessments. Kept for
provenance; not the current source of truth. Internal links inside archived docs
may point at their original (pre-reorg) locations.

- [archive/](archive/): the full archive (PRD, build plans, rebuild blueprint, embedding gap and fix plans, third-party and competitor assessments, the `superpowers/` phase plans and specs, and more).

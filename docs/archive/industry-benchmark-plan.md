# Industry Benchmark Plan

Current implementation and verification status lives in
[`current-status.md`](./current-status.md).

The fast showcase is real, but it is not the hours-long benchmark suite. It
proves that the product path works across backends. Claim-grade quality needs a
separate long-run lane.

## Benchmark Lanes

| Lane | Benchmark | What It Proves | Required Output |
| --- | --- | --- | --- |
| Long-term memory | LongMemEval | Recall across information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention | accuracy, recall@K, MRR, per-category scores, cost, wall time |
| Conversational memory | LoCoMo | Very long-term dialogue memory, temporal consistency, event recall | QA accuracy, temporal error rate, abstention behavior |
| RAG quality | RAGBench | Retrieval plus answer support over industry-style RAG examples | TRACe-style answer/retrieval metrics, citation/support labels |
| Long context | LongBench | Long-document QA, multi-document QA, summarization, synthetic tasks, code | score by task family and context length |
| Dynamic RAG | CRAG | Factual QA with changing/open-world data and mock APIs | exact match/F1, missing-info handling, API/tool cost |
| Multi-hop RAG | MultiHop-RAG | Retrieval over multiple supporting facts | recall@K, answer F1, support coverage |

## Long-Term Memory Comparables

These are not Stele clones, but they set user expectations for published
memory claims.

| System | Why It Matters | Comparison Axis |
| --- | --- | --- |
| Mem0 | Popular memory API for user facts and personalization | ease of integration, LOCOMO/LongMemEval-style recall |
| Zep / Graphiti | Temporal knowledge graph memory | mutable facts, temporal reasoning, entity state |
| Letta | Stateful agent framework with explicit memory tools | agentic memory operations, context paging |
| MemPalace | Local-first verbatim memory with public benchmark focus | local recall, MCP surface, reproducibility |
| Mastra Observational Memory | Published LongMemEval-focused memory design | prompt-stable observational memory |
| Supermemory | Published LongMemEval-S category breakdowns | temporal/update-heavy memory |
| LangMem / LangChain memory | Framework-native memory layer | integration and developer adoption |
| CrewAI / LlamaIndex memory | Common agent/workflow memory abstractions | ecosystem expectations |
| Pinecone Nexus | Managed agent knowledge layer with KnowQL, citations, governance, and token-reduction claims | enterprise knowledge-layer expectations, but not sovereign/local by default |

Strategic assessment for Pinecone Nexus lives in
[`pinecone-nexus-assessment.md`](./pinecone-nexus-assessment.md).

## Product-Specific Claims To Measure

Stele has to prove four things separately:

1. Prompt-payload reduction: replacement payload vs original artifact payload.
2. Accuracy preservation: answer quality relative to direct full-context baseline.
3. PII safety: model-visible summary/search/fetch surfaces do not leak configured PII.
4. Performance: ingestion, fetch, retrieval, cleanup, and backend-specific latency.

The minimum public claim bar remains:

- `>=90%` task accuracy relative to direct full-context baseline.
- Per-category recall numbers for long-term memory benchmarks.
- Explicit wall-clock runtime and API/model cost.
- Separate tables for fast smoke, local deterministic recall, and industry benchmark results.

## Local Long-Run Scenario Matrix

The repo now includes a broad deterministic benchmark lane:

```bash
scripts/run-long-benchmarks.sh
```

It runs `benchmarks.longrun` across every configured backend and writes:

- `benchmarks/runs/<date>/longrun-<run-id>/results.jsonl`
- `benchmarks/runs/<date>/longrun-<run-id>/LongRun.json`
- `benchmarks/runs/<date>/longrun-<run-id>/LongRun.md`
- `benchmarks/runs/latest-longrun.json`

The current local matrix has 35 scenario families:

- tool-output scenarios: legal, SQL, logs, JSON, code diff, CSV, HTML, Markdown, traces, tickets
- long-term memory scenarios: preferences, commitments, project decisions, cross-session synthesis
- temporal/update scenarios: old facts, current facts, changed preferences
- retrieval scenarios: abstention, multi-hop ownership, dependencies, needle placement
- PII scenarios: email, phone, SSN, credit card, API secret

Scale knobs:

```bash
YMS_LONGRUN_REPEAT=100 YMS_LONGRUN_CONTENT_MULTIPLIER=16 scripts/run-long-benchmarks.sh
```

The script is intentionally separate from the external industry dataset adapters.
It is useful for regression and product-claim discipline, but it is not a
substitute for LongMemEval, LoCoMo, RAGBench, LongBench, CRAG, or MultiHop-RAG.

## Answer Workflow / LLM Judge Lane

The repo also includes a strategy benchmark for the actual product question:

> What is the fastest, cheapest context path that lets the LLM answer correctly?

Run it against the local OpenAI-compatible model server:

```bash
scripts/run-answer-workflow-judge.sh
```

Defaults:

- base URL: `http://192.168.1.193:8000/v1`
- model: `Intel/Qwen3-Coder-Next-int4-AutoRound`
- strategies: `summary_only`, `summary_then_search`, `search_first`, `adaptive`, `raw_fetch`

Metrics:

- judged correctness
- judged context sufficiency
- estimated prompt tokens
- estimated completion tokens
- total estimated tokens
- LLM round trips
- stash search calls
- stash fetch calls
- context bytes
- latency

The intended decision rule is not "always retrieve chunks" or "always fetch raw."
It is to find the cheapest passing strategy per scenario. Some scenarios should
pass with the scrubbed summary alone. Some should require search. Some should
require raw fetch or richer chunk retrieval. Those differences are the benchmark.

## Sources To Track

- LongMemEval: https://github.com/xiaowu0162/LongMemEval
- LongMemEval paper: https://arxiv.org/abs/2410.10813
- LoCoMo paper: https://arxiv.org/abs/2402.17753
- RAGBench: https://huggingface.co/papers/2407.11005
- LongBench: https://aclanthology.org/2024.acl-long.172/
- CRAG: https://papers.nips.cc/paper_files/paper/2024/hash/1435d2d0fca85a84d83ddcb754f58c29-Abstract-Datasets_and_Benchmarks_Track.html
- MultiHop-RAG: https://huggingface.co/papers/2401.15391
- Mastra Observational Memory: https://mastra.ai/research/observational-memory
- Supermemory research: https://supermemory.ai/research/

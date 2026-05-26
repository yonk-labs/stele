# Agentic memory systems — benchmark landscape & honest comparison

Where stele sits among other agentic/LLM memory systems on the two benchmarks
we both run: **LoCoMo** and **LongMemEval**. Read the confounders section first
— **these numbers are not apples-to-apples**, and this doc does not claim a
head-to-head win.

## TL;DR

- The field's published LoCoMo numbers cluster at **66–76%** on an LLM-judge
  score — but under **GPT-4o / GPT-4o-mini** answerers and *each vendor's own
  harness*. The same system scores **58% / 66% / 75%** depending on who runs it
  (the documented Zep↔Mem0 dispute).
- stele's showcase used a **local quantized Qwen3-Coder** answerer + an
  independent **gemma-4-26B** judge — a deliberately harder, cheaper, fully
  local stack. So our absolute LoCoMo number (digest 0.50) is **not comparable**
  to a GPT-4o-mini 0.67.
- The defensible comparison stele owns is **within its own harness**: digest
  (lede summary + facts + top-5 chunks) vs full raw context — same answerer,
  same judge, same data. There, **digest matches or beats full context at
  8–10× fewer tokens**, and on **LongMemEval digest (0.75) beats full context
  (0.50)** — the denoising effect.
- A true cross-system comparison requires re-running rivals **inside one
  harness**. stele's `scripts/run-full-showcase.sh` is built to do exactly that.

## Published / claimed numbers (cited)

LoCoMo, LLM-judge "J" overall unless noted; answerer GPT-4o-mini unless noted:

| System | LoCoMo (J / metric) | Answer LLM | Source |
|---|---|---|---|
| Full-context baseline | **72.9%** (ceiling in Mem0's table) | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| Memobase | **75.78%** (temporal 85.05) | GPT-4o-mini | memobase GitHub/blog |
| Zep (self-reported) | **75.14%** | GPT-4o-mini | Zep "Lies, Damn Lies & Statistics" |
| Letta / MemGPT | **74.0%** (filesystem agent) | GPT-4o-mini | Letta benchmarking blog |
| Mem0ᵍ (graph) | **68.4%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| Mem0 | **66.9%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| Zep (as run by Mem0) | **65.99%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| RAG (best k=2) | **60.97%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| LangMem | **58.10%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| OpenAI memory | **52.9%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| A-Mem | **39.79%** | GPT-4o-mini | Mem0 arXiv 2504.19413 |
| cognee | F1 **0.841** / human-like 0.925 (DeepEval, *not* J) | unspecified | cognee.ai |
| LoCoMo paper | GPT-4 ≈ **32.1 F1** (partial-match F1, human ceiling 87.9) | GPT-4 | LoCoMo arXiv 2402.17753 |
| **stele — digest** | **0.50** (J via gemma judge) | **local Qwen3-Coder-int4** | this run |
| **stele — full context** | **0.556** | local Qwen3-Coder-int4 | this run |

LongMemEval, accuracy (GPT-4o judge in the published work):

| System | LongMemEval | Answer LLM | Source |
|---|---|---|---|
| Zep | **71.2%** | GPT-4o | Zep "State of the Art" |
| LongMemEval paper (oracle/offline) | **87–92%** | GPT-4o | arXiv 2410.10813 |
| Zep | **60.2%** | GPT-4o-mini | Zep "State of the Art" |
| LongMemEval paper (full-context ~115k tok) | **60.6–64%** | GPT-4o | arXiv 2410.10813 |
| Zep full-context baseline | 55.4% (mini) / 63.8% (4o) | GPT-4o(-mini) | Zep "State of the Art" |
| **stele — digest** | **0.75** (gemma judge) | **local Qwen3-Coder-int4** | this run |
| **stele — full context** | **0.50** | local Qwen3-Coder-int4 | this run |

> On LongMemEval, stele's digest (0.75, *local* answerer) lands above the
> published GPT-4o-mini memory numbers (~0.60) and full-context baselines
> (~0.55–0.64) — encouraging, but still a different harness/judge, so treat as
> directional, not a ranking.

## Why these are NOT apples-to-apples

1. **The metric "J" is overloaded.** Mem0 = LLM-as-judge; Zep called the same
   column Jaccard similarity; cognee = DeepEval correctness + a "human-like"
   score; the LoCoMo paper = partial-match F1; MemoryOS / A-Mem = F1/BLEU. A
   "0.67 J", a "0.84 F1", and a "32 F1" are three different rulers.
2. **Harness variance.** Zep claims Mem0 mis-ran it (both speakers as one role,
   appended timestamps, sequential search); same system → 58.44% / 65.99% /
   75.14% across reports. LoCoMo is notorious for this.
3. **Different answer LLMs.** Rivals: GPT-4o / GPT-4o-mini. stele: a local
   **int4-quantized coder** model — cheaper and fully local, but weaker on
   conversational QA, which depresses LoCoMo specifically.
4. **Different judges.** LongMemEval standardizes a GPT-4o judge (>97% human
   agreement); Mem0's judge is "a more capable LLM" (unspecified); stele uses
   gemma-4-26B. Judge choice alone moves scores several points.
5. **Different task shapes / subsets.** LongMemEval-S (~115k-token sessions) vs
   LoCoMo (~300-turn multi-session); category mixes and sampled subsets differ.
6. **Different units entirely.** Supermemory reports retrieval P@1 / Recall@10,
   not answer accuracy — not comparable to a J/F1 score at all.

## What stele can defensibly claim

- **Within-harness** (same answerer + judge + data): digest ≈ or > full context
  at 8–10× fewer tokens on real corpora; digest > full context on LongMemEval.
- **Operational facts** independent of the judge: 96.57% prompt-payload
  reduction across 4 engines, 0 PII leaks, 0.981 long-term-recall accuracy over
  a 2,625-run matrix (see `FULL-SHOWCASE-REPORT.md`).
- The **honest next step** for a real comparison: run Mem0 / Zep / Letta through
  `scripts/run-full-showcase.sh`'s answer-workflow with the same answerer +
  judge, on the same dataset slices. Until then, the table above is *citation*,
  not *ranking*.

## Sources

- Mem0 — https://arxiv.org/abs/2504.19413 · https://mem0.ai/research-3
- Zep (LongMemEval) — https://blog.getzep.com/state-of-the-art-agent-memory/
- Zep (LoCoMo critique) — https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
- Zep paper — https://arxiv.org/abs/2501.13956
- Letta — https://www.letta.com/blog/benchmarking-ai-agent-memory
- LongMemEval — https://arxiv.org/abs/2410.10813 · https://github.com/xiaowu0162/longmemeval
- LoCoMo — https://github.com/snap-research/locomo (arXiv 2402.17753)
- cognee — https://www.cognee.ai/research-and-evaluation-results
- Memobase — https://github.com/memodb-io/memobase/blob/main/docs/experiments/locomo-benchmark/README.md
- MemoryOS — https://arxiv.org/abs/2506.06326 · A-Mem — https://arxiv.org/abs/2502.12110
- Supermemory — https://supermemory.ai/blog/supermemory-vs-zep/

_Numbers retrieved 2026-05-26. Vendor leaderboards move; re-verify before citing externally._

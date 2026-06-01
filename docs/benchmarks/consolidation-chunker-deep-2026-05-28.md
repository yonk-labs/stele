# ConsolidationChunker — deeper test (n=100 LoCoMo, production-plumbed)

Follow-up to the 2026-05-28 n=30 bake-off. Implements `ConsolidationChunker`
as a first-class indexing option in stele core (`IndexingConfig.chunker =
"consolidation"`), adds a contract test, adds a `consolidation` strategy
lane to `answer_workflow.py`, and runs n=100 LoCoMo through the production
harness with both extractive and LLM consolidators. Same answerer
(gpt-4o-mini), same dataset, same judge plumbing as the prior n=100
same-ruler stele-vs-Mem0 table.

## What was implemented (PR scope)

- `src/stele/core/config.py` — `chunker: Literal["fixed_overlap", "consolidation"]`
  + `consolidator_module / consolidator_function / consolidator_kwargs /
  fact_max_chars`. Validator requires `consolidator_module` when chunker=
  consolidation.
- `src/stele/storage/chunk_store/_chunkshop_base.py` — builds chunkshop's
  `ConsolidationChunker(base=FixedOverlap, consolidator=Callable...)` when
  configured. **Plus a load-bearing fix**: surface `chunk.embedded_content`
  (post-distillation view) instead of `chunk.original_content` (full
  pre-distill text). For fixed_overlap they're identical; for consolidation,
  episodes' embedded content is the compressed summary. Caught while the
  consolidation lane was returning ~14k-token contexts and scoring 0.00.
- `benchmarks/answer_workflow.py` — new `consolidation` strategy + CLI flags
  `--chunker / --consolidator-module / --consolidator-kwargs`. The strategy
  packs context as structured `[SUMMARY]` + `[FACTS]` blocks via
  `SearchHit.metadata.kind` (also propagated by the chunk-store fix).
- `tests/contract/test_consolidation_chunker_contract.py` — episode+facts
  emission + vector ranking, parametrized across sqlite/postgres/mariadb/
  clickhouse (DSN-gated). All 822 unit+contract tests pass.

## How the bake was run

- Stele backend: sqlite (chunkshop-backed, fastembed embedder, sqlite-vec sink)
- Scenarios: LoCoMo, 10 conversations × 10 QA = n=100 (adversarial cat-5 skipped)
- Answerer: gpt-4o-mini (cheap baseline)
- Judge: gpt-4o with two prompts
  - In-bench default (the abstention-crediting one we caught earlier)
  - **`jscore` re-judge** (`rejudge_aw.py --prompt jscore`) — Mem0's verbatim
    published LoCoMo J-score prompt; abstention scores wrong
- Consolidators:
  - **extractive** — `benchmarks/external/consolidators/extractive.py`
    (deterministic, no API; midrange-sentence facts + word-capped summary)
  - **LLM** — `benchmarks/external/consolidators/llm.py` (gpt-4o-mini
    structured JSON: 120-word summary + ≤12 atomic SPO facts)

## Results — same harness, same answerer, same judge prompts

n=100, gpt-4o-mini answerer, gpt-4o judge.

| lane | acc (default judge) | **acc (jscore)** | mean prompt tokens | default-vs-jscore gap |
|---|---:|---:|---:|---:|
| raw_fetch | 0.39 | **0.34** | 10,374 | +0.05 |
| digest | 0.42 | **0.25** | 1,183 | +0.17 |
| consolidation_LLM (structured) | 0.70 | 0.16 | 502 | +0.54 |
| consolidation_LLM (raw concat) | 0.71 | 0.17 | 342 | +0.54 |
| consolidation_extractive (structured) | 0.94 | 0.07 | 553 | **+0.87** |
| consolidation_extractive (raw concat) | 0.90 | 0.09 | 432 | **+0.81** |
| search_first | 0.41 | 0.01 | 145 | +0.40 |

The default-judge column is misleading on its own (we know it credits
abstentions). The jscore column is the load-bearing one.

## Honest findings

1. **The implementation works.** Contract test passes on sqlite + postgres
   (chunkshop-backed paths). 822 unit+contract tests stay green. The
   `consolidation` lane is now a first-class production option behind a
   public config knob.

2. **The lane is real but doesn't win.** Under jscore (Mem0's own published
   ruler), consolidation_LLM at **0.17 / 342 tokens** is competitive with
   Mem0's prior 0.18 / ~540 tokens on the same dataset — same neighborhood.
   But it's **strictly dominated by stele's existing `digest` lane** (0.25
   / 1,183 tokens), which trades ~2.5× the tokens for ~50% more accuracy.

3. **`consolidation_extractive` is genuinely bad** at 0.07–0.09 jscore.
   Placeholder SVO triples (subject = first token, predicate = second
   token, object = next three) and a naive first-120-word summary don't
   carry enough information; the model abstains ~80% of the time. A real
   extractive (proper SVO via dependency parse, or distillation by an
   actual extractor) would need building before claiming any extractive
   variant is viable.

4. **Structure didn't help.** Same chunks, presented as raw concatenation
   vs `[SUMMARY]\n...\n[FACTS]\n- s|p|o :: span\n...`, scored within noise
   (0.17 vs 0.16 LLM; 0.09 vs 0.07 extractive). The gap to digest isn't
   about formatting — it's that the distilled view is too lossy at this
   answerer/dataset.

5. **Biggest default-judge inflation ever measured.** consolidation_extractive
   showed a **+0.87 gap between default and jscore** (0.94 → 0.07). The
   compressed view makes the model abstain a lot; the default judge credits
   abstention; the apparent "94% accuracy" was ~87 percentage points of
   abstention credit and ~7 points of real correct answers. This is why
   jscore (or strict-bench) is non-negotiable for any cross-system claim.

6. **Mem0-tier, not stele-tier.** Both consolidation lanes land in the
   Mem0-style token budget (~342–553 tokens) at roughly Mem0-tier
   accuracy under jscore. They don't reach digest's 0.25 ceiling on this
   answerer. If you want minimum tokens at acceptable accuracy, consolidation
   is a viable option; if you want best-accuracy-at-moderate-tokens, digest
   wins.

## What changed vs the n=30 bake's directional read

The n=30 bake suggested extractive at 0.20 jscore. At n=100 it dropped to
0.09. The likely causes, in order:
- **Small-N noise.** A 6-question difference (12/30 vs 9/100) on this dataset
  isn't significant.
- **Different harness.** The n=30 bake used a custom driver with the full
  consolidator output in context; n=100 uses the production strategy's
  top-15 vector hits. Both cover the chunks; the formatting differs and
  it didn't matter (verified by the structured re-run above).
- **n=100 is the more reliable number.** Trust the larger sample.

## When this lane makes sense

- You're token-bound and 0.16 jscore is enough accuracy
- You want a fast (extractive) or LLM-distilled compact memory record per
  artifact and don't need stele's full digest stack
- You're comparing apples-to-apples with Mem0-style ingest pipelines

## When it doesn't

- You're targeting best-accuracy-at-bounded-cost: use `digest` (0.25 jscore /
  ~1.2k tokens) instead
- You can afford full context: use `raw_fetch` (0.34 jscore / ~10k tokens)
- You're using `consolidation_extractive` with the placeholder consolidator
  in this repo — don't, it's a baseline scaffold not a recommended setup

## Artifacts

- `docs/benchmarks/consolidation-chunker-deep-2026-05-28/` — n=100 runs:
  baseline (digest/raw_fetch/search_first), consolidation+extractive,
  consolidation+LLM, both consolidation re-runs with structured context, +
  jscore re-judge JSON for each
- Implementation: `src/stele/core/config.py`,
  `src/stele/storage/chunk_store/_chunkshop_base.py`,
  `benchmarks/answer_workflow.py`,
  `tests/contract/test_consolidation_chunker_contract.py`

## Addendum (2026-05-28 PM) — pushing jscore past 0.20

The gpt-4o-mini consolidation numbers above (~0.16-0.18 jscore) prompted the
question: what actually moves jscore up? We ran an ablation. The answer was
NOT what we tuned first.

### What we tried, in order

| change | LLM-lane jscore | note |
|---|---:|---|
| v1 raw concat | 0.17 | baseline |
| v2 structured [SUMMARY]/[FACTS] | 0.16 | formatting — no help |
| v3 + hybrid retrieval + max_facts=25 | **0.19** | retrieval mode + budget — small help |
| v4 + verbatim-date/entity prompt | 0.18 | consolidator prompt — no help (noise) |

Prompt/retrieval/formatting tuning **plateaued at ~0.18** for gpt-4o-mini.
That bouncing 0.16-0.19 is single-run noise around one ceiling.

### The actual lever: the answerer

Holding the best consolidation config fixed (LLM consolidator, hybrid
retrieval, max_facts=25), we swept the answerer model:

| answerer | consolidation jscore | default judge | mean tokens | abstention rate |
|---|---:|---:|---:|---:|
| gpt-4o | 0.09 | 0.53 | 516 | ~80% |
| gpt-4o-mini | 0.18 | 0.63 | 501 | ~75% |
| **qwen3-coder** | **0.30** | 0.60 | 501 | **46%** |

**qwen clears 0.20 comfortably at 0.30 jscore**, ~500 tokens. The driver is
abstention behavior, not reasoning quality: gpt-4o is the strongest model
but scores LOWEST because it honestly abstains when the distilled context is
thin, and jscore gives no credit for "I do not have enough information."
qwen commits to a best-guess answer and collects partial credit. This is the
SAME answerer-dominates-everything pattern the judge-reliability study found
for `digest` (qwen 0.43 vs gpt-4o 0.18 on identical retrieval).

### Where consolidation-qwen lands on the same-ruler table

| lane (qwen answerer, jscore) | accuracy | mean tokens |
|---|---:|---:|
| stele raw_fetch | 0.53 | ~10,000 |
| stele digest | 0.43 | ~1,300 |
| Mem0 | 0.34 | ~540 |
| **stele consolidation (LLM)** | **0.30** | **~500** |

At ~500 tokens, consolidation-qwen (0.30) is just below Mem0 (0.34) at the
same budget, and below digest (0.43) at ~2.6× fewer tokens. So the honest
"how do we exceed 0.20" answer: **use a committal answerer** — that alone
moves consolidation from 0.18 to 0.30. The consolidator/retrieval tuning was
a sideshow; the answerer is the main act.

### What we did NOT do (would push higher, separate scope)

- **Per-session consolidation.** Still one consolidation pass per multi-
  session conversation. Per-session (date-stamped summary+facts per session,
  like Mem0's ingest) is the remaining structural lever, est. +0.05-0.15.
- **Committal-prompt the answerer.** A "never abstain; always give your best
  single guess" answerer instruction would raise jscore for the cautious
  OpenAI models too — but that's gaming the abstention-credit dynamic, not
  improving recall, so we left it out.

## Verdict

The chunkshop ConsolidationChunker is now a first-class stele indexing
option, the contract is enforced, and a fair n=100 measurement says:
**with a committal answerer it reaches 0.30 jscore at ~500 tokens —
Mem0-competitive, still below stele's own digest (0.43).** The single
biggest lever for the headline number is the answerer, not the consolidator.
The default-judge inflation for compression-heavy lanes is the cautionary-
tale finding — 0.94 → 0.07 (extractive) is the kind of number that would
have shipped as the headline in any benchmark that didn't validate its judge.

## Addendum 2 (2026-05-29) — date-header fix, extractive rewrite, store-vs-retrieve, gpt-5

Three structural probes after the answerer ablation. All n=100 LoCoMo, jscore.

### a) Extractive consolidator rewrite (free, deterministic)

The original extractive scored sentences by length-proximity-to-80-chars and
truncated spans mid-word — garbage fragments, ~0.07 jscore. Rewrote it to
segment into speaker-attributed sentences, rank by answer-bearing density
(dates/numbers/proper-nouns), and keep WHOLE sentences. Result:

| consolidator | answerer | jscore | cost |
|---|---|---:|---|
| old extractive | gpt-4o-mini | ~0.07 | free |
| new extractive | gpt-4o-mini | 0.24 | free |
| LLM (gpt-4o-mini) | qwen | 0.30 | API |
| Mem0 (reference) | qwen | 0.34 | API |
| **new extractive** | **qwen** | **0.38** | **free** |

The free deterministic extractive BEATS the LLM consolidator and Mem0 on the
same ruler — because it keeps verbatim spans (dates/numbers intact) while the
LLM paraphrases and drops specifics. For fact recall, selection > generation.

### b) Session-date-header fix — helps full context, NOT distilled lanes

The LoCoMo builder silently dropped `session_N_date_time` (a string, skipped
by the turn-list filter), so dialogue carried only RELATIVE dates while gold
answers are absolute. Injected `[Session date: ...]` headers. Effect (qwen):

| lane | jscore w/o fix | jscore w/ fix |
|---|---:|---:|
| raw_fetch | 0.53 | **0.58** |
| consolidation (extractive) | 0.38 | 0.37 |
| digest | 0.43 | 0.36 |

Only raw_fetch benefited. Distillation/retrieval SEPARATES the date anchor
(its own chunk) from the relative-date fact, so they rarely co-occur in a
retrieved set. Only full context lets the model do "last Friday" + "session
was 8 May" resolution. Distillation actively breaks temporal reasoning.

### c) Store-many / retrieve-few — hypothesis FALSIFIED for this task

RAG theory says: store a rich pool (mf=40), retrieve a tight top-k so search
selects best fits. We added a `STELE_CONS_RETRIEVE_K` knob to decouple
stored-count from retrieved-count and tested it (store=40):

| retrieve-k | answerer | jscore | abstention | mean tokens |
|---:|---|---:|---:|---:|
| 8 | qwen | 0.28 | 52% | 210 |
| 25 | qwen | **0.33** | 52% | 638 |
| 8 | gpt-5 | 0.12 | 80% | 210 |

Tight retrieval scored LOWER. Same abstention rate at k=8 vs k=25, but k=25
was right more often — because hybrid/vector retrieval can't reliably rank the
date/number fact into the top-8 (the embedding weakness: "7 May" and "12 May"
embed nearly identically). So "retrieve few" = gamble the answer-bearing fact
is in the top-8, and it usually isn't. **For LoCoMo, recall beats precision.**

### d) gpt-5 as answerer — worse, not better

gpt-5 (store40/ret8) scored 0.12 — the LOWEST of any answerer — at 80%
abstention. gpt-5 is the most cautious model; starve it and it refuses. Its
default-judge 0.66 vs jscore 0.12 is a +0.54 abstention-credit gap, the
largest in the study. The bottleneck is willingness-to-commit + retrieval
recall, NOT answerer reasoning. A newer/smarter model made it worse.

### Bottom line

The free rewritten extractive (qwen, 0.38) is the best consolidation result —
Mem0-beating, digest-adjacent, zero API cost. But the lane's ceiling is
structural: distillation strips the date anchors temporal questions need, and
retrieval can't rank dates/numbers to compensate. Full context (raw_fetch
0.58) remains the accuracy ceiling; digest (~0.36-0.43) the
accuracy-per-token sweet spot; consolidation the minimum-token option.

## Addendum 3 (2026-05-29) — winning temporal: attach the session date

LoCoMo temporal gold answers are frequently phrased relative-to-session ("the
week before 9 June 2023", "the sunday before 25 May 2023") and the dialogue
only carries relative dates. Root cause of the temporal ceiling: chunking
separates the relative expression ("last Friday") from its session-date anchor.
Fix: carry the date WITH each fact. Added `date_mode` to the extractive
consolidator (extractive + qwen + retrieve-25, jscore):

| date_mode | mechanism | jscore | default judge |
|---|---|---:|---:|
| none | baseline | 0.37 | 0.61 |
| anchor | prefix `(around 8 May 2023)` per fact | 0.36 | 0.67 |
| resolve | compute + append `[date: 5 May 2023]` | 0.37 | 0.69 |
| **both** | anchor + resolve | **0.39** | 0.66 |
| both (gpt-4o-mini answerer) | — | 0.22 | **0.80** |

**Half-win, and the judge gap proves it.** Default judge leapt (0.61→0.69) but
jscore moved only +0.02 (0.37→0.39). Anchoring made the model STOP abstaining
and ATTEMPT temporal answers (default-judge credits attempts) — but it resolves
to the wrong date too often: wrong session ("23 June" when gold is "7 May") or
wrong offset direction ("27 May" vs "the Sunday before 25 May"). jscore's
±14-day tolerance credits near-misses, not wrong-session picks.

The gpt-4o-mini row is the cautionary headline: **0.80 default judge, 0.22
jscore — a +0.58 abstention/near-miss-credit gap, the largest in the study.**
Date scaffolding makes a weak answerer attempt everything and look spectacular
on the default judge while being wrong most of the time.

**Conclusion.** Attaching the source date is necessary and unblocks the
question type, but the new bottleneck is RETRIEVAL PRECISION — surfacing the
*right* fact's session — not date arithmetic. `both`-qwen 0.39 is a new
consolidation high but marginal. The architecturally correct fix is not more
date-in-text hacking; it's date/identity as a FILTERABLE FIELD + filter-then-
rank retrieval — see `docs/session-memory-metadata-design.md`.

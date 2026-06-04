# Hybrid Search Best Practices — Getting Hybrid *Right*

Companion to [retrieval-tuning-guide.md](retrieval-tuning-guide.md). That guide
helps you **pick** an engine (keyword / hybrid / graph). This one is about the
*internals* of hybrid once you've chosen it — the unglamorous correctness knobs
that decide whether your fusion actually surfaces the answer.

Every number below is from a measured run in this repo (postgres / pgvector,
bge-base-en-v1.5, sentence_aware chunker, gemma-4-26B jscore judge with Mem0's
prompt, abstention = wrong). The slice is small and honest: 5 LoCoMo
conversations, n=50 questions, answer-dense. Treat the **directions** as durable
and the **decimals** as directional. LoCoMo numbers are not comparable across
vendors/harnesses — only same-harness deltas here are defensible.

> **TL;DR of what actually moved the needle:** a one-line bug fix (return full
> chunks, not snippets) and the *packing* strategy (date-resolved facts for
> temporal questions). The things people usually tune — distance metric, retrieval
> architecture, chunk size — were non-levers or a wash on a fair field.

---

## 1. Strip stopwords *and* punctuation from the keyword query

In an OR-joined keyword/FTS query, function words are pure noise — every chunk
contains "the", "with", "and", so they let topically-irrelevant chunks score and
drown the high-signal terms.

**Bad** (raw query split on whitespace):
```
"When" OR "did" OR "Caroline" OR "meet" OR "up" OR "with" OR "her"
  OR "friends," OR "family," OR "and" OR "mentors?"
```
Note the punctuation glued to terms — `"friends,"` won't match `friends`.

**Good** (`content_terms()` strips stopwords + punctuation, dedups):
```
"caroline" OR "meet" OR "friends" OR "family" OR "mentors"
```

In stele this lives in `stele.retrieval.rank.content_terms()` and is shared by
both keyword paths (`keyword_score` and sqlite's `_fts_query`). Effect on the
canonical hard question ("When did Caroline meet up with her friends, family, and
mentors?"): the answer chunk went from **absent in the top-10 → rank 9**.
Necessary, not sufficient — see §4.

> Postgres's `websearch_to_tsquery('english', …)` already removes English
> stopwords and applies AND semantics. The sqlite/chunk path was the one carrying
> raw tokens. Worth knowing your backend's tokenizer differs.

---

## 2. Return full chunks, not snippets (the bug that masqueraded as a feature)

This was the single highest-impact fix in the whole investigation, and it was a
one-line bug. In RRF fusion, when a chunk is hit by *both* the keyword and vector
paths, you have to choose which hit's **text** represents it. The keyword path
carries a ~500-char snippet; the vector path carries the full chunk. stele was
picking the **snippet**:

```python
# before — keyword snippet wins (contradicts the code's own comment)
for hit in [*kw, *vec]:
    rep.setdefault(_key(hit), hit)

# after — vector full-text wins
for hit in [*vec, *kw]:
    rep.setdefault(_key(hit), hit)
```

Before the fix, **8 of 10** chunks returned by hybrid mode were 503-char
snippets (truncated mid-sentence with `…`) instead of full ~2,900-char chunks.
The model was answering on a third of the context it should have had.

**The deeper lesson:** this bug also faked a benchmark result. An early
"cascade beats RRF 6-to-4" finding evaporated once both lanes returned full
chunks — the cascades had simply been packing 3× more text. **A correctness bug
will impersonate an architecture win. Audit what bytes actually reach the model
before you believe a retrieval comparison.**

Rule: **truncate at display, never inside the retrieval path.**

---

## 3. The distance metric is a non-lever on normalized embeddings

People love to A/B cosine vs L2 vs dot-product. On normalized embeddings (bge,
most modern sentence encoders — verify with `mean ‖v‖ ≈ 1.0`), don't bother. For
unit vectors all three are monotone transforms of the same dot product vᵀq:

- cosine = vᵀq
- L2² = 2 − 2·vᵀq
- inner product = vᵀq

So they produce **provably identical rankings**. Measured on pgvector 0.8.2 with
real bge vectors, the answer chunk sat at rank 39 under `<=>`, `<->`, and `<#>`
with identical top-5. Only L1/Manhattan (`<+>`) reorders at all — and it moved
the answer a whole two places (39 → 37). Hamming/Jaccard are bit-vector only.

| pgvector operator | metric | answer rank |
|---|---|---|
| `<=>` | cosine | 39 |
| `<->` | L2 | 39 (identical top-5) |
| `<#>` | inner product | 39 (identical top-5) |
| `<+>` | L1 / Manhattan | 37 |

If your vectors are normalized, spend the energy you'd spend on metric tuning on
§4 instead.

---

## 4. Packing beats retrieval architecture — and the best packing is query-type-specific

Holding the chunker substrate constant, we crossed 3 retrieval architectures × 3
packings (n=50). Two findings:

**(a) Retrieval architecture barely matters on a fair field.**

| retrieval | jscore |
|---|---|
| cascade_b (semantic-net → keyword-rerank) | 0.700 |
| rrf (current default) | 0.693 |
| cascade_a (FTS-first → semantic-rerank) | 0.660 |

cascade_b vs rrf is a third of one question — noise. Keep RRF as the default;
it's simpler and already shipped. (The cascade *mechanic* still matters in
specific cases — see §6.)

**(b) Packing is the real lever, and it splits hard by question type.**

| packing | overall | temporal Qs (n=20) | non-temporal Qs (n=30) |
|---|---|---|---|
| raw chunks | 0.680 | 0.65–0.70 | **0.67–0.73** |
| lede digest | 0.647 | 0.65–0.70 | 0.60–0.67 |
| **digest + facts** | **0.727** | **0.80–0.85** | 0.67–0.70 |

- **For "when / how-long" questions, append date-resolved facts.** stele's
  extractive consolidator emits speaker-attributed spans with `[date: ISO]`
  resolved from the session anchor, so the date and the "last Friday" never get
  separated by chunking. That's +0.15–0.20 on temporal questions.
- **For non-temporal questions, raw chunks win.** Don't pay the packing tax when
  the answer isn't a date/fact.
- **Plain lede digest is the worst packing everywhere** — summarization strips the
  answer-bearing specifics. It only becomes a winner once you append the facts.

Top single configuration overall (tied): `rrf + facts` and `cascade_b + facts`,
both 0.74.

---

## 5. There is no universal best — measure on *your* query mix

§4 is the whole argument for not hard-coding a default. Exact signals
(keyword/FTS/metadata predicates) win factoid, temporal, and named-entity
queries because the answer is a specific token or date. Embeddings win
paraphrase and conceptual queries where there's no lexical overlap. Which
dominates is a property of **your** corpus and query log, not a universal truth.

Roadmap item (`stele tune`): a periodic bake-off that scores retrieval × packing
on the user's own data and rewrites the configured default. Until that ships, the
safe defaults are: **hybrid (RRF) retrieval + full chunks + facts-packing if your
workload is temporal-heavy, raw chunks otherwise.**

---

## 6. When cascade ordering *does* matter (and which way)

RRF with `rrf_k=60` and a `limit*2` over-fetch can't rescue a chunk that's strong
on one axis but weak on the other: at `limit=10` the over-fetch pool is 20, so a
vector hit at rank 22 never even enters fusion. If you have queries where one
signal is reliably strong and the other weak, a cascade helps — but **order it
correctly**:

- **cascade_b = wide semantic net → keyword rerank.** The rerank (second) stage
  decides final order, so it must carry the *strong/exact* signal; the first
  stage only needs to be a net wide enough to contain the answer. This is
  "exact-signal ranks, semantic recalls."
- **cascade_a = FTS-first → semantic rerank** under-performed, because its rerank
  stage re-sorts by the weaker semantic signal and demotes the exact match.

Knob in stele: the candidate pool (we used 30) feeding the rerank, then top-k.
On our mixed slice the cascade didn't beat RRF overall — reach for it only when
you know your query shape.

---

## Non-levers — things we burned time on so you don't have to

- **Distance metric** on normalized vectors (§3) — provably can't help.
- **Chunk size as a "fix."** Shrinking chunks concentrates a specific answer's
  embedding (q07's answer jumped from rank 39 → #0 at 500 chars) but trades away
  context for questions that need surrounding turns. It's a precision/coverage
  *dial*, not a bug fix. Don't chase it before fixing §1 and §2.
- **Retrieval architecture** (§4a) — a wash once you return full chunks.
- **Expanded/synonym hints** — marginal in earlier runs.

## Related

- [retrieval-tuning-guide.md](retrieval-tuning-guide.md) — pick the engine first.
- [vector-indexing-setup.md](vector-indexing-setup.md) — chunkshop / embedding setup.
- [filtered-retrieval.md](filtered-retrieval-guide.md) — metadata + temporal filters.
- Investigation narrative + raw numbers:
  [benchmarks/retrieval-investigation-log.md](../benchmarks/findings/retrieval-investigation-log.md).

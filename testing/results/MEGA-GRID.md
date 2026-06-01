# Mega benchmark grid: every lane x corpus (post-fix)

## How to read this grid

Each row is one **recipe** (a "lane") run against one **corpus**, scored on the same
questions by the same judge. Higher `jscore` = more right answers; lower `~tokens` =
cheaper context. The only hard part is decoding the lane name.

### `system` (who produced the row)

| name | what it is |
|---|---|
| `stele-highN` | stele, the **confident** runs (n≈250). These are the numbers to trust. |
| `stele-sweep` | stele, a wide **exploratory** sweep (n=40). Directional only; small samples flip. |
| `letta-archival` | Letta (a competitor) in its archival-memory mode. |
| `letta-agent` | Letta in agent mode. An **interrupted** n=20 run that scored 0.00; kept as a record, *not* a fair number. |
| `mem0-local` | Mem0 (a competitor), using a local LLM to boil docs down to atomic facts. |
| `PARAMETRIC-FLOOR` | The control: answer with **no memory at all**. Whatever the model scores here it already knew, so subtract it before believing any row. |

### `lane` (the recipe)

**Every lane is a full recipe: chunker + retrieval + packing + knobs.** The lane *name*
only spells out the axes that **changed** in that experiment. Anything the name leaves out
sits at the default:

> chunker = `sentence_aware` · retrieval = `hybrid` · packing = `raw` · index = `hnsw` · neighbor = on

So `nb1_k=10` is the defaults with neighbor **on** and the **top-10** chunks fed (it comes
from a neighbor/k sweep, so only those two move; retrieval is still hybrid, packing still
raw). `hybrid_raw_hnsw` is those same defaults written out in full. What each lane name
overrides:

| lane shape | what it changes vs the default | reading |
|---|---|---|
| `raw_fetch` | no retrieval; feeds the **whole document** | the ceiling (packing is moot) |
| `keyword`, `cascade_b_hnsw` | the **retrieval** step | keyword-only / vector-then-keyword |
| `hybrid_facts_hnsw`, `hybrid_digest_hnsw` | the **packing** | facts list / query-digest, not raw |
| `hybrid_raw_exact` | the **index** (brute-force, not HNSW) | the exact-vs-HNSW test |
| `nb1_k=N`, `nb0_k=N` | **neighbor** on/off + how many **chunks** (k) | `nb0_k=5` = neighbor off, top-5 |
| `digest_mix` | the **packing** (digest + facts + top-3 raw) | the kitchen sink |
| `digest_expanded` | **packing** = digest with synonym-**expanded** hints | |
| `enriching_digest`, `enriching_facts` | the **chunker** (enriching) + packing | |
| `A:<chunker>+<packing>` | **chunker x packing** (sweep family A); retrieval stays hybrid | `A:sentence_aware+facts` |
| `B:<retrieval>+<packing>` | **retrieval x packing** (sweep family B); chunker stays sentence_aware | `B:cascade_b+raw` |
| `C:hints-<none\|expanded>+<packing>` | **hints x packing** (sweep family C) | `C:hints-expanded+digest` |
| `D:<chunker>+<retrieval>+<packing>` | the **factorial fill** of the missing interaction cells (n=40) | `D:enriching+cascade_b+digest` |
| `(memory)` | a competitor's own end-to-end pipeline; not comparable axis-by-axis | |

The building blocks those names draw from:

**Chunkers** (how a doc is sliced before indexing): `sentence_aware` = sentence boundaries,
~1000 chars (default) · `fixed_overlap` = blind fixed windows · `consolidation` /
`enriching` = squeeze the doc into extracted facts.

**Retrieval** (how chunks are picked per question): `hybrid` = vector + keyword fused via
RRF (default) · `keyword` = full-text only (the *old* default; note how close it sits to
the floor) · `cascade_a` = keyword-first then vector re-rank · `cascade_b` = vector-first
then keyword re-rank · `raw_fetch` = skip retrieval, feed the whole document.

**Packing** (how chunks are formatted for the model): `raw` = verbatim · `digest` =
query-focused summary + top-5 chunks · `facts` = digest + extracted fact list ·
`digest_mix` = digest + facts + top-3 raw chunks.

**Knobs:** `hnsw` = approximate vector index (default) vs `exact` = brute-force scan ·
`nb1`/`nb0` = neighbor window on/off · `k=N` = how many chunks were fed.

### Columns

`chunker` · `retrieval` · `packing` · `knobs` = the lane decoded into its four axes, so you
don't have to parse the codename (`knobs` packs index·neighbor·k). The values repeat a lot
across rows; that's expected. Then the scores:

`jscore` = fraction the judge marked correct (gemma-4-26B, **abstention = wrong**), 0 to 1 ·
`mrr` = how near the top the right chunk ranked, 1/rank averaged (stele-only; competitor
memories are abstractive, shown as a dash) · `~tokens` ≈ ctx_chars/4 (cost axis) ·
`retr_ms` / `ans_ms` = retrieval / answer latency · `n` = questions in that cell.


> **Rows are split by sample size** so the comparison is apples to apples. `n≈250` is the confident tier (trust these); `n≤40` is directional breadth (small samples flip, treat as hints, not verdicts).


## locomo

### n≈250 (confident)

| system | lane | chunker | retrieval | packing | knobs | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| stele-highN | raw_fetch | sentence_aware | (whole doc) | raw | — | 0.84 | 0.34 | 19776 | 0.0 | 2135.2 | 250 |
| stele-highN | nb1_k=20 | sentence_aware | hybrid | raw | hnsw·nb1·k=20 | 0.74 | 0.167 | 13807 | 57.3 | 3128.6 | 250 |
| stele-highN | cascade_b_hnsw | sentence_aware | cascade_b | raw | hnsw·nb1·k=10 | 0.71 | 0.149 | 7039 | 64.9 | 2874.9 | 250 |
| stele-highN | hybrid_raw_exact | sentence_aware | hybrid | raw | exact·nb1·k=10 | 0.71 | 0.163 | 6191 | 33.5 | 1168.2 | 250 |
| stele-highN | hybrid_raw_hnsw | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.70 | 0.163 | 6191 | 32.8 | 2680.4 | 250 |
| stele-highN | nb1_k=10 | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.70 | 0.163 | 7026 | 57.3 | 1904.6 | 250 |
| stele-highN | nb0_k=20 | sentence_aware | hybrid | raw | hnsw·nb0·k=20 | 0.68 | 0.12 | 4738 | 53.9 | 1682.5 | 250 |
| stele-highN | digest_mix | sentence_aware | hybrid | digest_mix | hnsw·nb1·k=20 | 0.67 | 0.151 | 3773 | 57.3 | 2003.7 | 250 |
| stele-highN | hybrid_facts_hnsw | sentence_aware | hybrid | facts | hnsw·nb1·k=10 | 0.64 | 0.163 | 4716 | 32.8 | 2330.2 | 250 |
| stele-highN | digest_expanded | sentence_aware | hybrid | digest (expanded hints) | hnsw·nb1·k=10 | 0.64 | 0.156 | 4306 | 29.1 | 2013.6 | 250 |
| stele-highN | nb1_k=5 | sentence_aware | hybrid | raw | hnsw·nb1·k=5 | 0.63 | 0.157 | 3489 | 57.3 | 1128.2 | 250 |
| stele-highN | nb0_k=10 | sentence_aware | hybrid | raw | hnsw·nb0·k=10 | 0.63 | 0.118 | 2408 | 53.9 | 1081.6 | 250 |
| stele-highN | nb1_k=3 | sentence_aware | hybrid | raw | hnsw·nb1·k=3 | 0.60 | 0.151 | 2076 | 57.3 | 894.6 | 250 |
| stele-highN | hybrid_digest_hnsw | sentence_aware | hybrid | digest | hnsw·nb1·k=10 | 0.60 | 0.163 | 4381 | 52.0 | 3071.5 | 250 |
| stele-highN | nb0_k=5 | sentence_aware | hybrid | raw | hnsw·nb0·k=5 | 0.58 | 0.112 | 1210 | 53.9 | 760.9 | 250 |
| letta-archival | (memory) | — | — | — | — | 0.56 | — | 1757 | 407.3 | 2117.9 | 250 |
| stele-highN | enriching_digest | enriching | hybrid | digest | hnsw·nb1·k=10 | 0.54 | 0.208 | 18786 | 26.8 | 2635.8 | 250 |
| stele-highN | enriching_facts | enriching | hybrid | facts | hnsw·nb1·k=10 | 0.54 | 0.208 | 19108 | 26.8 | 1415.3 | 250 |
| stele-highN | nb0_k=3 | sentence_aware | hybrid | raw | hnsw·nb0·k=3 | 0.52 | 0.103 | 724 | 53.9 | 627.9 | 250 |
| stele-highN | nb1_k=1 | sentence_aware | hybrid | raw | hnsw·nb1·k=1 | 0.43 | 0.128 | 683 | 57.3 | 489.6 | 250 |
| stele-highN | nb0_k=1 | sentence_aware | hybrid | raw | hnsw·nb0·k=1 | 0.38 | 0.072 | 240 | 53.9 | 325.8 | 250 |
| mem0-local | (memory) | — | — | — | — | 0.11 | — | 462 | 122.6 | 951.5 | 250 |
| stele-highN | keyword | sentence_aware | keyword | raw | hnsw·nb1·k=10 | 0.05 | 0.024 | 89 | 14.9 | 274.5 | 250 |
| PARAMETRIC-FLOOR | (no context) | — | — | — | — | 0.00 | — | 0 | — | — | 250 |

### n≤40 (directional)

| system | lane | chunker | retrieval | packing | knobs | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| stele-sweep | D:enriching+cascade_a+facts | enriching | cascade_a | facts | hnsw·nb1·k=10 | 0.82 | 0.229 | 26026 | 49.6 | 1650.2 | 40 |
| stele-sweep | raw_fetch | sentence_aware | (whole doc) | raw | — | 0.80 | 0.275 | 17869 | 0.0 | 1740.7 | 40 |
| stele-sweep | D:enriching+cascade_a+raw | enriching | cascade_a | raw | hnsw·nb1·k=10 | 0.78 | 0.229 | 23895 | 49.6 | 4198.5 | 40 |
| stele-sweep | A:sentence_aware+facts | sentence_aware | hybrid | facts | hnsw·nb1·k=10 | 0.75 | 0.138 | 4550 | 33.9 | 989.8 | 40 |
| stele-sweep | B:cascade_b+raw | sentence_aware | cascade_b | raw | hnsw·nb1·k=10 | 0.75 | 0.13 | 7020 | 62.6 | 2420.3 | 40 |
| stele-sweep | B:cascade_b+facts | sentence_aware | cascade_b | facts | hnsw·nb1·k=10 | 0.75 | 0.13 | 4824 | 62.6 | 832.8 | 40 |
| stele-sweep | D:enriching+cascade_b+raw | enriching | cascade_b | raw | hnsw·nb1·k=10 | 0.75 | 0.275 | 23920 | 52.1 | 1398.1 | 40 |
| stele-sweep | D:enriching+cascade_b+digest | enriching | cascade_b | digest | hnsw·nb1·k=10 | 0.75 | 0.275 | 25677 | 52.1 | 3159.9 | 40 |
| stele-sweep | D:enriching+cascade_b+facts | enriching | cascade_b | facts | hnsw·nb1·k=10 | 0.75 | 0.275 | 26056 | 52.1 | 1230.8 | 40 |
| stele-sweep | C:hints-none+facts | sentence_aware | hybrid | facts (none hints) | hnsw·nb1·k=10 | 0.72 | 0.138 | 4550 | 33.9 | 865.3 | 40 |
| stele-sweep | D:enriching+cascade_a+digest | enriching | cascade_a | digest | hnsw·nb1·k=10 | 0.72 | 0.229 | 25649 | 49.6 | 6022.9 | 40 |
| stele-sweep | A:fixed_overlap+raw | fixed_overlap | hybrid | raw | hnsw·nb1·k=10 | 0.70 | 0.131 | 4338 | 28.9 | 1577.2 | 40 |
| stele-sweep | A:fixed_overlap+facts | fixed_overlap | hybrid | facts | hnsw·nb1·k=10 | 0.68 | 0.131 | 3559 | 28.9 | 765.8 | 40 |
| stele-sweep | A:sentence_aware+raw | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.68 | 0.138 | 6044 | 33.9 | 1997.2 | 40 |
| stele-sweep | B:cascade_a+raw | sentence_aware | cascade_a | raw | hnsw·nb1·k=10 | 0.68 | 0.114 | 7009 | 62.8 | 2481.6 | 40 |
| stele-sweep | B:cascade_b+digest | sentence_aware | cascade_b | digest | hnsw·nb1·k=10 | 0.68 | 0.13 | 4479 | 62.6 | 1733.5 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+facts | fixed_overlap | cascade_b | facts | hnsw·nb1·k=10 | 0.68 | 0.106 | 3685 | 53.6 | 788.3 | 40 |
| stele-sweep | B:cascade_a+facts | sentence_aware | cascade_a | facts | hnsw·nb1·k=10 | 0.65 | 0.114 | 4763 | 62.8 | 892.3 | 40 |
| stele-sweep | C:hints-none+digest | sentence_aware | hybrid | digest (none hints) | hnsw·nb1·k=10 | 0.65 | 0.138 | 4225 | 33.9 | 668.2 | 40 |
| stele-sweep | C:hints-expanded+digest | sentence_aware | hybrid | digest (expanded hints) | hnsw·nb1·k=10 | 0.65 | 0.138 | 4231 | 33.9 | 1789.6 | 40 |
| stele-sweep | C:hints-expanded+facts | sentence_aware | hybrid | facts (expanded hints) | hnsw·nb1·k=10 | 0.65 | 0.138 | 4556 | 33.9 | 836.0 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+facts | fixed_overlap | cascade_a | facts | hnsw·nb1·k=10 | 0.65 | 0.12 | 3696 | 47.9 | 791.5 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+digest | fixed_overlap | cascade_b | digest | hnsw·nb1·k=10 | 0.65 | 0.106 | 3351 | 53.6 | 1397.2 | 40 |
| stele-sweep | A:fixed_overlap+digest | fixed_overlap | hybrid | digest | hnsw·nb1·k=10 | 0.62 | 0.131 | 3226 | 28.9 | 1303.9 | 40 |
| stele-sweep | A:sentence_aware+digest | sentence_aware | hybrid | digest | hnsw·nb1·k=10 | 0.62 | 0.138 | 4225 | 33.9 | 1802.1 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+raw | fixed_overlap | cascade_a | raw | hnsw·nb1·k=10 | 0.62 | 0.12 | 4881 | 47.9 | 1788.1 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+raw | fixed_overlap | cascade_b | raw | hnsw·nb1·k=10 | 0.60 | 0.106 | 4908 | 53.6 | 1751.5 | 40 |
| stele-sweep | B:cascade_a+digest | sentence_aware | cascade_a | digest | hnsw·nb1·k=10 | 0.57 | 0.114 | 4419 | 62.8 | 1995.9 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+digest | fixed_overlap | cascade_a | digest | hnsw·nb1·k=10 | 0.53 | 0.12 | 3364 | 47.9 | 1252.3 | 40 |
| stele-sweep | D:consolidation+cascade_a+raw | consolidation | cascade_a | raw | hnsw·nb1·k=10 | 0.45 | 0.062 | 285 | 45.4 | 560.3 | 40 |
| stele-sweep | D:consolidation+cascade_b+raw | consolidation | cascade_b | raw | hnsw·nb1·k=10 | 0.45 | 0.048 | 337 | 40.3 | 558.9 | 40 |
| stele-sweep | A:consolidation+digest | consolidation | hybrid | digest | hnsw·nb1·k=10 | 0.42 | 0.071 | 1136 | 26.5 | 881.8 | 40 |
| stele-sweep | D:consolidation+cascade_a+digest | consolidation | cascade_a | digest | hnsw·nb1·k=10 | 0.42 | 0.062 | 1064 | 45.4 | 818.5 | 40 |
| stele-sweep | D:consolidation+cascade_b+digest | consolidation | cascade_b | digest | hnsw·nb1·k=10 | 0.42 | 0.048 | 1206 | 40.3 | 820.2 | 40 |
| stele-sweep | D:consolidation+cascade_b+facts | consolidation | cascade_b | facts | hnsw·nb1·k=10 | 0.42 | 0.048 | 1388 | 40.3 | 625.3 | 40 |
| stele-sweep | A:consolidation+raw | consolidation | hybrid | raw | hnsw·nb1·k=10 | 0.40 | 0.071 | 304 | 26.5 | 488.4 | 40 |
| stele-sweep | A:enriching+digest | enriching | hybrid | digest | hnsw·nb1·k=10 | 0.40 | 0.1 | 9423 | 28.3 | 2246.4 | 40 |
| stele-sweep | A:enriching+facts | enriching | hybrid | facts | hnsw·nb1·k=10 | 0.40 | 0.1 | 9678 | 28.3 | 1014.9 | 40 |
| stele-sweep | A:consolidation+facts | consolidation | hybrid | facts | hnsw·nb1·k=10 | 0.38 | 0.071 | 1308 | 26.5 | 585.7 | 40 |
| stele-sweep | A:enriching+raw | enriching | hybrid | raw | hnsw·nb1·k=10 | 0.38 | 0.1 | 8440 | 28.3 | 1429.4 | 40 |
| stele-sweep | D:consolidation+cascade_a+facts | consolidation | cascade_a | facts | hnsw·nb1·k=10 | 0.38 | 0.062 | 1229 | 45.4 | 581.9 | 40 |
| stele-sweep | B:keyword+raw | sentence_aware | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.05 | 91 | 13.9 | 252.3 | 40 |
| stele-sweep | B:keyword+digest | sentence_aware | keyword | digest | hnsw·nb1·k=10 | 0.15 | 0.05 | 228 | 13.9 | 291.9 | 40 |
| stele-sweep | B:keyword+facts | sentence_aware | keyword | facts | hnsw·nb1·k=10 | 0.15 | 0.05 | 322 | 13.9 | 224.6 | 40 |
| stele-sweep | D:fixed_overlap+keyword+raw | fixed_overlap | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.05 | 91 | 13.5 | 254.7 | 40 |
| stele-sweep | D:fixed_overlap+keyword+digest | fixed_overlap | keyword | digest | hnsw·nb1·k=10 | 0.15 | 0.05 | 228 | 13.5 | 457.7 | 40 |
| stele-sweep | D:fixed_overlap+keyword+facts | fixed_overlap | keyword | facts | hnsw·nb1·k=10 | 0.15 | 0.05 | 322 | 13.5 | 225.0 | 40 |
| stele-sweep | D:consolidation+keyword+raw | consolidation | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.05 | 91 | 14.0 | 252.2 | 40 |
| stele-sweep | D:consolidation+keyword+digest | consolidation | keyword | digest | hnsw·nb1·k=10 | 0.15 | 0.05 | 228 | 14.0 | 363.9 | 40 |
| stele-sweep | D:consolidation+keyword+facts | consolidation | keyword | facts | hnsw·nb1·k=10 | 0.15 | 0.05 | 322 | 14.0 | 207.2 | 40 |
| stele-sweep | D:enriching+keyword+raw | enriching | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.05 | 91 | 14.0 | 251.3 | 40 |
| stele-sweep | D:enriching+keyword+digest | enriching | keyword | digest | hnsw·nb1·k=10 | 0.15 | 0.05 | 228 | 14.0 | 307.0 | 40 |
| stele-sweep | D:enriching+keyword+facts | enriching | keyword | facts | hnsw·nb1·k=10 | 0.15 | 0.05 | 322 | 14.0 | 207.0 | 40 |
| letta-agent | (memory) | — | — | — | — | 0.00 | — | — | — | — | 20 |


## ragbench-hotpotqa

### n≈250 (confident)

| system | lane | chunker | retrieval | packing | knobs | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| stele-highN | cascade_b_hnsw | sentence_aware | cascade_b | raw | hnsw·nb1·k=10 | 0.94 | 0.885 | 1157 | 48.9 | 564.0 | 250 |
| stele-highN | nb0_k=10 | sentence_aware | hybrid | raw | hnsw·nb0·k=10 | 0.94 | 0.823 | 498 | 28.0 | 418.7 | 250 |
| stele-highN | raw_fetch | sentence_aware | (whole doc) | raw | — | 0.94 | 0.904 | 500 | 0.0 | 517.5 | 250 |
| stele-highN | hybrid_raw_exact | sentence_aware | hybrid | raw | exact·nb1·k=10 | 0.94 | 0.889 | 1010 | 27.0 | 444.1 | 250 |
| stele-highN | nb1_k=5 | sentence_aware | hybrid | raw | hnsw·nb1·k=5 | 0.94 | 0.889 | 1000 | 39.6 | 508.9 | 250 |
| stele-highN | hybrid_raw_hnsw | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.94 | 0.889 | 1010 | 26.2 | 622.6 | 250 |
| stele-highN | enriching_facts | enriching | hybrid | facts | hnsw·nb1·k=10 | 0.94 | 0.904 | 1905 | 22.1 | 530.2 | 250 |
| stele-highN | nb1_k=3 | sentence_aware | hybrid | raw | hnsw·nb1·k=3 | 0.94 | 0.889 | 872 | 39.6 | 579.4 | 250 |
| stele-highN | nb1_k=10 | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.94 | 0.889 | 1010 | 39.6 | 433.0 | 250 |
| stele-highN | nb0_k=5 | sentence_aware | hybrid | raw | hnsw·nb0·k=5 | 0.94 | 0.823 | 495 | 28.0 | 448.7 | 250 |
| stele-highN | nb1_k=20 | sentence_aware | hybrid | raw | hnsw·nb1·k=20 | 0.93 | 0.889 | 1010 | 39.6 | 441.6 | 250 |
| stele-highN | hybrid_facts_hnsw | sentence_aware | hybrid | facts | hnsw·nb1·k=10 | 0.93 | 0.889 | 2605 | 26.2 | 1076.3 | 250 |
| stele-highN | enriching_digest | enriching | hybrid | digest | hnsw·nb1·k=10 | 0.93 | 0.904 | 1533 | 22.1 | 786.7 | 250 |
| stele-highN | hybrid_digest_hnsw | sentence_aware | hybrid | digest | hnsw·nb1·k=10 | 0.92 | 0.889 | 2235 | 38.8 | 1613.2 | 250 |
| stele-highN | nb0_k=20 | sentence_aware | hybrid | raw | hnsw·nb0·k=20 | 0.92 | 0.823 | 498 | 28.0 | 420.6 | 250 |
| stele-highN | digest_expanded | sentence_aware | hybrid | digest (expanded hints) | hnsw·nb1·k=10 | 0.92 | 0.889 | 2239 | 34.4 | 969.4 | 250 |
| stele-highN | nb0_k=3 | sentence_aware | hybrid | raw | hnsw·nb0·k=3 | 0.92 | 0.821 | 450 | 28.0 | 468.3 | 250 |
| letta-archival | (memory) | — | — | — | — | 0.92 | — | 500 | 368.0 | 977.2 | 250 |
| stele-highN | digest_mix | sentence_aware | hybrid | digest_mix | hnsw·nb1·k=20 | 0.92 | 0.889 | 2479 | 39.6 | 1038.2 | 250 |
| stele-highN | nb1_k=1 | sentence_aware | hybrid | raw | hnsw·nb1·k=1 | 0.88 | 0.876 | 398 | 39.6 | 445.6 | 250 |
| stele-highN | nb0_k=1 | sentence_aware | hybrid | raw | hnsw·nb0·k=1 | 0.62 | 0.78 | 186 | 28.0 | 357.3 | 250 |
| mem0-local | (memory) | — | — | — | — | 0.44 | — | 139 | 155.2 | 700.5 | 250 |
| stele-highN | keyword | sentence_aware | keyword | raw | hnsw·nb1·k=10 | 0.20 | 0.228 | 64 | 2.1 | 244.6 | 250 |
| PARAMETRIC-FLOOR | (no context) | — | — | — | — | 0.02 | — | 0 | — | — | 250 |

### n≤40 (directional)

| system | lane | chunker | retrieval | packing | knobs | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| stele-sweep | B:cascade_b+raw | sentence_aware | cascade_b | raw | hnsw·nb1·k=10 | 0.97 | 0.887 | 1228 | 52.6 | 558.8 | 40 |
| stele-sweep | B:cascade_b+digest | sentence_aware | cascade_b | digest | hnsw·nb1·k=10 | 0.97 | 0.887 | 2768 | 52.6 | 578.4 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+raw | fixed_overlap | cascade_b | raw | hnsw·nb1·k=10 | 0.97 | 0.9 | 579 | 43.4 | 478.5 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+digest | fixed_overlap | cascade_b | digest | hnsw·nb1·k=10 | 0.97 | 0.9 | 1665 | 43.4 | 624.1 | 40 |
| stele-sweep | D:enriching+cascade_a+raw | enriching | cascade_a | raw | hnsw·nb1·k=10 | 0.97 | 0.9 | 579 | 46.9 | 586.1 | 40 |
| stele-sweep | A:fixed_overlap+raw | fixed_overlap | hybrid | raw | hnsw·nb1·k=10 | 0.95 | 0.9 | 579 | 62.5 | 593.1 | 40 |
| stele-sweep | A:sentence_aware+raw | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.95 | 0.887 | 1094 | 24.4 | 702.0 | 40 |
| stele-sweep | A:sentence_aware+digest | sentence_aware | hybrid | digest | hnsw·nb1·k=10 | 0.95 | 0.887 | 2513 | 24.4 | 1033.0 | 40 |
| stele-sweep | A:enriching+raw | enriching | hybrid | raw | hnsw·nb1·k=10 | 0.95 | 0.875 | 562 | 26.9 | 572.5 | 40 |
| stele-sweep | B:cascade_a+raw | sentence_aware | cascade_a | raw | hnsw·nb1·k=10 | 0.95 | 0.875 | 1228 | 53.4 | 711.3 | 40 |
| stele-sweep | B:cascade_a+digest | sentence_aware | cascade_a | digest | hnsw·nb1·k=10 | 0.95 | 0.875 | 2767 | 53.4 | 985.6 | 40 |
| stele-sweep | B:cascade_a+facts | sentence_aware | cascade_a | facts | hnsw·nb1·k=10 | 0.95 | 0.875 | 3138 | 53.4 | 622.9 | 40 |
| stele-sweep | B:cascade_b+facts | sentence_aware | cascade_b | facts | hnsw·nb1·k=10 | 0.95 | 0.887 | 3138 | 52.6 | 502.5 | 40 |
| stele-sweep | C:hints-none+digest | sentence_aware | hybrid | digest (none hints) | hnsw·nb1·k=10 | 0.95 | 0.887 | 2513 | 24.4 | 491.4 | 40 |
| stele-sweep | C:hints-expanded+digest | sentence_aware | hybrid | digest (expanded hints) | hnsw·nb1·k=10 | 0.95 | 0.887 | 2513 | 24.4 | 1026.9 | 40 |
| stele-sweep | raw_fetch | sentence_aware | (whole doc) | raw | — | 0.95 | 0.9 | 526 | 0.0 | 676.8 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+raw | fixed_overlap | cascade_a | raw | hnsw·nb1·k=10 | 0.95 | 0.875 | 579 | 43.8 | 597.4 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+digest | fixed_overlap | cascade_a | digest | hnsw·nb1·k=10 | 0.95 | 0.875 | 1665 | 43.8 | 1012.1 | 40 |
| stele-sweep | D:enriching+cascade_a+digest | enriching | cascade_a | digest | hnsw·nb1·k=10 | 0.95 | 0.9 | 1667 | 46.9 | 661.4 | 40 |
| stele-sweep | D:enriching+cascade_b+raw | enriching | cascade_b | raw | hnsw·nb1·k=10 | 0.95 | 0.9 | 579 | 47.0 | 462.1 | 40 |
| stele-sweep | D:enriching+cascade_b+digest | enriching | cascade_b | digest | hnsw·nb1·k=10 | 0.95 | 0.9 | 1667 | 47.0 | 539.3 | 40 |
| stele-sweep | A:fixed_overlap+digest | fixed_overlap | hybrid | digest | hnsw·nb1·k=10 | 0.93 | 0.9 | 1665 | 62.5 | 848.8 | 40 |
| stele-sweep | A:fixed_overlap+facts | fixed_overlap | hybrid | facts | hnsw·nb1·k=10 | 0.93 | 0.9 | 2033 | 62.5 | 637.9 | 40 |
| stele-sweep | A:sentence_aware+facts | sentence_aware | hybrid | facts | hnsw·nb1·k=10 | 0.93 | 0.887 | 2884 | 24.4 | 636.0 | 40 |
| stele-sweep | A:enriching+digest | enriching | hybrid | digest | hnsw·nb1·k=10 | 0.93 | 0.875 | 1622 | 26.9 | 742.4 | 40 |
| stele-sweep | C:hints-none+facts | sentence_aware | hybrid | facts (none hints) | hnsw·nb1·k=10 | 0.93 | 0.887 | 2884 | 24.4 | 487.2 | 40 |
| stele-sweep | C:hints-expanded+facts | sentence_aware | hybrid | facts (expanded hints) | hnsw·nb1·k=10 | 0.93 | 0.887 | 2884 | 24.4 | 604.9 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+facts | fixed_overlap | cascade_a | facts | hnsw·nb1·k=10 | 0.93 | 0.875 | 2034 | 43.8 | 634.6 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+facts | fixed_overlap | cascade_b | facts | hnsw·nb1·k=10 | 0.93 | 0.9 | 2033 | 43.4 | 497.1 | 40 |
| stele-sweep | D:enriching+cascade_a+facts | enriching | cascade_a | facts | hnsw·nb1·k=10 | 0.93 | 0.9 | 2037 | 46.9 | 537.8 | 40 |
| stele-sweep | D:enriching+cascade_b+facts | enriching | cascade_b | facts | hnsw·nb1·k=10 | 0.93 | 0.9 | 2037 | 47.0 | 475.5 | 40 |
| stele-sweep | A:enriching+facts | enriching | hybrid | facts | hnsw·nb1·k=10 | 0.90 | 0.875 | 1985 | 26.9 | 542.6 | 40 |
| stele-sweep | D:consolidation+cascade_a+raw | consolidation | cascade_a | raw | hnsw·nb1·k=10 | 0.80 | 0.566 | 453 | 50.4 | 710.5 | 40 |
| stele-sweep | A:consolidation+raw | consolidation | hybrid | raw | hnsw·nb1·k=10 | 0.78 | 0.752 | 469 | 26.6 | 545.4 | 40 |
| stele-sweep | A:consolidation+facts | consolidation | hybrid | facts | hnsw·nb1·k=10 | 0.75 | 0.752 | 1727 | 26.6 | 553.9 | 40 |
| stele-sweep | D:consolidation+cascade_a+digest | consolidation | cascade_a | digest | hnsw·nb1·k=10 | 0.75 | 0.566 | 1380 | 50.4 | 775.5 | 40 |
| stele-sweep | D:consolidation+cascade_b+raw | consolidation | cascade_b | raw | hnsw·nb1·k=10 | 0.75 | 0.734 | 472 | 45.3 | 771.7 | 40 |
| stele-sweep | A:consolidation+digest | consolidation | hybrid | digest | hnsw·nb1·k=10 | 0.72 | 0.752 | 1422 | 26.6 | 745.3 | 40 |
| stele-sweep | D:consolidation+cascade_a+facts | consolidation | cascade_a | facts | hnsw·nb1·k=10 | 0.72 | 0.566 | 1674 | 50.4 | 545.5 | 40 |
| stele-sweep | D:consolidation+cascade_b+facts | consolidation | cascade_b | facts | hnsw·nb1·k=10 | 0.72 | 0.734 | 1749 | 45.3 | 884.6 | 40 |
| stele-sweep | D:consolidation+cascade_b+digest | consolidation | cascade_b | digest | hnsw·nb1·k=10 | 0.65 | 0.734 | 1449 | 45.3 | 881.8 | 40 |
| stele-sweep | B:keyword+facts | sentence_aware | keyword | facts | hnsw·nb1·k=10 | 0.17 | 0.2 | 245 | 2.1 | 310.9 | 40 |
| stele-sweep | D:fixed_overlap+keyword+facts | fixed_overlap | keyword | facts | hnsw·nb1·k=10 | 0.17 | 0.2 | 245 | 4.1 | 312.8 | 40 |
| stele-sweep | D:consolidation+keyword+facts | consolidation | keyword | facts | hnsw·nb1·k=10 | 0.17 | 0.2 | 245 | 2.1 | 271.3 | 40 |
| stele-sweep | D:enriching+keyword+facts | enriching | keyword | facts | hnsw·nb1·k=10 | 0.17 | 0.2 | 245 | 2.1 | 272.1 | 40 |
| stele-sweep | B:keyword+raw | sentence_aware | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.2 | 50 | 2.1 | 230.4 | 40 |
| stele-sweep | B:keyword+digest | sentence_aware | keyword | digest | hnsw·nb1·k=10 | 0.15 | 0.2 | 194 | 2.1 | 312.1 | 40 |
| stele-sweep | D:fixed_overlap+keyword+raw | fixed_overlap | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.2 | 50 | 4.1 | 231.1 | 40 |
| stele-sweep | D:consolidation+keyword+raw | consolidation | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.2 | 50 | 2.1 | 240.0 | 40 |
| stele-sweep | D:consolidation+keyword+digest | consolidation | keyword | digest | hnsw·nb1·k=10 | 0.15 | 0.2 | 194 | 2.1 | 268.1 | 40 |
| stele-sweep | D:enriching+keyword+raw | enriching | keyword | raw | hnsw·nb1·k=10 | 0.15 | 0.2 | 50 | 2.1 | 229.3 | 40 |
| stele-sweep | D:fixed_overlap+keyword+digest | fixed_overlap | keyword | digest | hnsw·nb1·k=10 | 0.12 | 0.2 | 194 | 4.1 | 282.4 | 40 |
| stele-sweep | D:enriching+keyword+digest | enriching | keyword | digest | hnsw·nb1·k=10 | 0.12 | 0.2 | 194 | 2.1 | 251.8 | 40 |
| letta-agent | (memory) | — | — | — | — | 0.00 | — | — | — | — | 20 |


## ragbench-covidqa

### n≈250 (confident)

| system | lane | chunker | retrieval | packing | knobs | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| stele-highN | hybrid_raw_hnsw | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.78 | 0.841 | 1368 | 25.6 | 1122.8 | 246 |
| stele-highN | digest_expanded | sentence_aware | hybrid | digest (expanded hints) | hnsw·nb1·k=10 | 0.78 | 0.841 | 2841 | 46.4 | 1525.9 | 246 |
| stele-highN | hybrid_raw_exact | sentence_aware | hybrid | raw | exact·nb1·k=10 | 0.78 | 0.841 | 1368 | 26.5 | 880.1 | 246 |
| stele-highN | cascade_b_hnsw | sentence_aware | cascade_b | raw | hnsw·nb1·k=10 | 0.77 | 0.842 | 1399 | 48.8 | 1016.2 | 246 |
| stele-highN | nb1_k=5 | sentence_aware | hybrid | raw | hnsw·nb1·k=5 | 0.77 | 0.841 | 1368 | 36.8 | 936.7 | 246 |
| stele-highN | digest_mix | sentence_aware | hybrid | digest_mix | hnsw·nb1·k=20 | 0.77 | 0.84 | 2935 | 36.8 | 1518.8 | 246 |
| stele-highN | hybrid_digest_hnsw | sentence_aware | hybrid | digest | hnsw·nb1·k=10 | 0.77 | 0.841 | 2839 | 39.1 | 2832.6 | 246 |
| stele-highN | nb1_k=10 | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.77 | 0.841 | 1368 | 36.8 | 884.7 | 246 |
| stele-highN | nb1_k=20 | sentence_aware | hybrid | raw | hnsw·nb1·k=20 | 0.77 | 0.841 | 1368 | 36.8 | 874.9 | 246 |
| stele-highN | enriching_digest | enriching | hybrid | digest | hnsw·nb1·k=10 | 0.76 | 0.882 | 1939 | 32.8 | 1293.7 | 246 |
| stele-highN | enriching_facts | enriching | hybrid | facts | hnsw·nb1·k=10 | 0.76 | 0.882 | 2242 | 32.8 | 1020.0 | 246 |
| stele-highN | nb1_k=3 | sentence_aware | hybrid | raw | hnsw·nb1·k=3 | 0.76 | 0.84 | 1144 | 36.8 | 1051.9 | 246 |
| stele-highN | hybrid_facts_hnsw | sentence_aware | hybrid | facts | hnsw·nb1·k=10 | 0.76 | 0.841 | 3159 | 25.6 | 1561.8 | 246 |
| stele-highN | raw_fetch | sentence_aware | (whole doc) | raw | — | 0.75 | 0.882 | 580 | 0.0 | 882.4 | 246 |
| stele-highN | nb0_k=10 | sentence_aware | hybrid | raw | hnsw·nb0·k=10 | 0.75 | 0.677 | 563 | 27.6 | 787.0 | 246 |
| stele-highN | nb0_k=20 | sentence_aware | hybrid | raw | hnsw·nb0·k=20 | 0.75 | 0.677 | 563 | 27.6 | 752.7 | 246 |
| letta-archival | (memory) | — | — | — | — | 0.74 | — | 580 | 452.9 | 1581.7 | 246 |
| stele-highN | nb0_k=5 | sentence_aware | hybrid | raw | hnsw·nb0·k=5 | 0.74 | 0.677 | 563 | 27.6 | 827.9 | 246 |
| stele-highN | nb0_k=3 | sentence_aware | hybrid | raw | hnsw·nb0·k=3 | 0.74 | 0.672 | 477 | 27.6 | 797.0 | 246 |
| stele-highN | nb1_k=1 | sentence_aware | hybrid | raw | hnsw·nb1·k=1 | 0.72 | 0.813 | 388 | 36.8 | 746.0 | 246 |
| stele-highN | nb0_k=1 | sentence_aware | hybrid | raw | hnsw·nb0·k=1 | 0.63 | 0.593 | 179 | 27.6 | 529.1 | 246 |
| stele-highN | keyword | sentence_aware | keyword | raw | hnsw·nb1·k=10 | 0.35 | 0.232 | 50 | 2.1 | 314.5 | 246 |
| mem0-local | (memory) | — | — | — | — | 0.14 | — | 26 | 70.6 | 507.5 | 246 |
| PARAMETRIC-FLOOR | (no context) | — | — | — | — | 0.04 | — | 0 | — | — | 246 |

### n≤40 (directional)

| system | lane | chunker | retrieval | packing | knobs | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| stele-sweep | D:enriching+cascade_a+digest | enriching | cascade_a | digest | hnsw·nb1·k=10 | 0.80 | 0.85 | 2000 | 89.4 | 1130.0 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+digest | fixed_overlap | cascade_a | digest | hnsw·nb1·k=10 | 0.78 | 0.838 | 1984 | 43.0 | 1173.8 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+facts | fixed_overlap | cascade_a | facts | hnsw·nb1·k=10 | 0.78 | 0.838 | 2274 | 43.0 | 976.4 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+digest | fixed_overlap | cascade_b | digest | hnsw·nb1·k=10 | 0.78 | 0.85 | 1999 | 45.9 | 842.4 | 40 |
| stele-sweep | D:enriching+cascade_b+digest | enriching | cascade_b | digest | hnsw·nb1·k=10 | 0.78 | 0.85 | 2000 | 41.4 | 993.7 | 40 |
| stele-sweep | A:fixed_overlap+digest | fixed_overlap | hybrid | digest | hnsw·nb1·k=10 | 0.75 | 0.85 | 1999 | 43.0 | 1211.2 | 40 |
| stele-sweep | A:fixed_overlap+facts | fixed_overlap | hybrid | facts | hnsw·nb1·k=10 | 0.75 | 0.85 | 2289 | 43.0 | 952.3 | 40 |
| stele-sweep | A:enriching+digest | enriching | hybrid | digest | hnsw·nb1·k=10 | 0.75 | 0.85 | 2000 | 31.3 | 1212.5 | 40 |
| stele-sweep | A:enriching+facts | enriching | hybrid | facts | hnsw·nb1·k=10 | 0.75 | 0.85 | 2292 | 31.3 | 1026.9 | 40 |
| stele-sweep | D:fixed_overlap+cascade_a+raw | fixed_overlap | cascade_a | raw | hnsw·nb1·k=10 | 0.75 | 0.838 | 648 | 43.0 | 859.7 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+facts | fixed_overlap | cascade_b | facts | hnsw·nb1·k=10 | 0.75 | 0.85 | 2290 | 45.9 | 839.6 | 40 |
| stele-sweep | D:enriching+cascade_a+facts | enriching | cascade_a | facts | hnsw·nb1·k=10 | 0.75 | 0.85 | 2292 | 89.4 | 905.8 | 40 |
| stele-sweep | A:sentence_aware+raw | sentence_aware | hybrid | raw | hnsw·nb1·k=10 | 0.72 | 0.825 | 1309 | 31.4 | 1096.2 | 40 |
| stele-sweep | A:sentence_aware+facts | sentence_aware | hybrid | facts | hnsw·nb1·k=10 | 0.72 | 0.825 | 3178 | 31.4 | 921.7 | 40 |
| stele-sweep | A:consolidation+raw | consolidation | hybrid | raw | hnsw·nb1·k=10 | 0.72 | 0.461 | 490 | 32.9 | 793.2 | 40 |
| stele-sweep | A:enriching+raw | enriching | hybrid | raw | hnsw·nb1·k=10 | 0.72 | 0.85 | 658 | 31.3 | 846.7 | 40 |
| stele-sweep | B:cascade_a+raw | sentence_aware | cascade_a | raw | hnsw·nb1·k=10 | 0.72 | 0.812 | 1350 | 53.8 | 995.5 | 40 |
| stele-sweep | B:cascade_a+digest | sentence_aware | cascade_a | digest | hnsw·nb1·k=10 | 0.72 | 0.812 | 2923 | 53.8 | 1273.9 | 40 |
| stele-sweep | B:cascade_a+facts | sentence_aware | cascade_a | facts | hnsw·nb1·k=10 | 0.72 | 0.812 | 3226 | 53.8 | 941.3 | 40 |
| stele-sweep | B:cascade_b+raw | sentence_aware | cascade_b | raw | hnsw·nb1·k=10 | 0.72 | 0.812 | 1350 | 49.9 | 860.2 | 40 |
| stele-sweep | B:cascade_b+digest | sentence_aware | cascade_b | digest | hnsw·nb1·k=10 | 0.72 | 0.812 | 2925 | 49.9 | 1039.3 | 40 |
| stele-sweep | C:hints-expanded+digest | sentence_aware | hybrid | digest (expanded hints) | hnsw·nb1·k=10 | 0.72 | 0.825 | 2873 | 31.4 | 1375.8 | 40 |
| stele-sweep | C:hints-expanded+facts | sentence_aware | hybrid | facts (expanded hints) | hnsw·nb1·k=10 | 0.72 | 0.825 | 3178 | 31.4 | 998.8 | 40 |
| stele-sweep | raw_fetch | sentence_aware | (whole doc) | raw | — | 0.72 | 0.85 | 568 | 0.0 | 882.6 | 40 |
| stele-sweep | D:enriching+cascade_a+raw | enriching | cascade_a | raw | hnsw·nb1·k=10 | 0.72 | 0.85 | 658 | 89.4 | 807.0 | 40 |
| stele-sweep | D:enriching+cascade_b+facts | enriching | cascade_b | facts | hnsw·nb1·k=10 | 0.72 | 0.85 | 2292 | 41.4 | 891.1 | 40 |
| stele-sweep | A:fixed_overlap+raw | fixed_overlap | hybrid | raw | hnsw·nb1·k=10 | 0.70 | 0.85 | 657 | 43.0 | 919.3 | 40 |
| stele-sweep | A:sentence_aware+digest | sentence_aware | hybrid | digest | hnsw·nb1·k=10 | 0.70 | 0.825 | 2873 | 31.4 | 1474.7 | 40 |
| stele-sweep | A:consolidation+facts | consolidation | hybrid | facts | hnsw·nb1·k=10 | 0.70 | 0.461 | 1546 | 32.9 | 745.2 | 40 |
| stele-sweep | D:fixed_overlap+cascade_b+raw | fixed_overlap | cascade_b | raw | hnsw·nb1·k=10 | 0.70 | 0.85 | 658 | 45.9 | 746.9 | 40 |
| stele-sweep | D:consolidation+cascade_a+digest | consolidation | cascade_a | digest | hnsw·nb1·k=10 | 0.70 | 0.397 | 1192 | 45.9 | 861.7 | 40 |
| stele-sweep | D:consolidation+cascade_b+raw | consolidation | cascade_b | raw | hnsw·nb1·k=10 | 0.70 | 0.447 | 493 | 47.7 | 721.6 | 40 |
| stele-sweep | D:enriching+cascade_b+raw | enriching | cascade_b | raw | hnsw·nb1·k=10 | 0.70 | 0.85 | 658 | 41.4 | 700.4 | 40 |
| stele-sweep | B:cascade_b+facts | sentence_aware | cascade_b | facts | hnsw·nb1·k=10 | 0.68 | 0.812 | 3232 | 49.9 | 820.3 | 40 |
| stele-sweep | C:hints-none+digest | sentence_aware | hybrid | digest (none hints) | hnsw·nb1·k=10 | 0.68 | 0.825 | 2873 | 31.4 | 824.7 | 40 |
| stele-sweep | C:hints-none+facts | sentence_aware | hybrid | facts (none hints) | hnsw·nb1·k=10 | 0.68 | 0.825 | 3178 | 31.4 | 724.2 | 40 |
| stele-sweep | D:consolidation+cascade_a+facts | consolidation | cascade_a | facts | hnsw·nb1·k=10 | 0.68 | 0.397 | 1405 | 45.9 | 706.6 | 40 |
| stele-sweep | D:consolidation+cascade_b+digest | consolidation | cascade_b | digest | hnsw·nb1·k=10 | 0.68 | 0.447 | 1315 | 47.7 | 991.0 | 40 |
| stele-sweep | A:consolidation+digest | consolidation | hybrid | digest | hnsw·nb1·k=10 | 0.65 | 0.461 | 1311 | 32.9 | 926.2 | 40 |
| stele-sweep | D:consolidation+cascade_a+raw | consolidation | cascade_a | raw | hnsw·nb1·k=10 | 0.65 | 0.397 | 407 | 45.9 | 729.2 | 40 |
| stele-sweep | D:consolidation+cascade_b+facts | consolidation | cascade_b | facts | hnsw·nb1·k=10 | 0.65 | 0.447 | 1545 | 47.7 | 703.3 | 40 |
| stele-sweep | D:fixed_overlap+keyword+raw | fixed_overlap | keyword | raw | hnsw·nb1·k=10 | 0.35 | 0.25 | 55 | 4.5 | 342.5 | 40 |
| stele-sweep | D:fixed_overlap+keyword+digest | fixed_overlap | keyword | digest | hnsw·nb1·k=10 | 0.35 | 0.25 | 233 | 4.5 | 419.1 | 40 |
| stele-sweep | D:fixed_overlap+keyword+facts | fixed_overlap | keyword | facts | hnsw·nb1·k=10 | 0.35 | 0.25 | 288 | 4.5 | 421.8 | 40 |
| stele-sweep | D:consolidation+keyword+raw | consolidation | keyword | raw | hnsw·nb1·k=10 | 0.35 | 0.25 | 55 | 2.1 | 326.2 | 40 |
| stele-sweep | D:consolidation+keyword+digest | consolidation | keyword | digest | hnsw·nb1·k=10 | 0.35 | 0.25 | 233 | 2.1 | 403.9 | 40 |
| stele-sweep | D:consolidation+keyword+facts | consolidation | keyword | facts | hnsw·nb1·k=10 | 0.35 | 0.25 | 288 | 2.1 | 378.2 | 40 |
| stele-sweep | D:enriching+keyword+raw | enriching | keyword | raw | hnsw·nb1·k=10 | 0.35 | 0.25 | 55 | 2.1 | 322.6 | 40 |
| stele-sweep | D:enriching+keyword+digest | enriching | keyword | digest | hnsw·nb1·k=10 | 0.35 | 0.25 | 233 | 2.1 | 405.1 | 40 |
| stele-sweep | B:keyword+raw | sentence_aware | keyword | raw | hnsw·nb1·k=10 | 0.33 | 0.25 | 55 | 2.2 | 353.6 | 40 |
| stele-sweep | B:keyword+digest | sentence_aware | keyword | digest | hnsw·nb1·k=10 | 0.33 | 0.25 | 233 | 2.2 | 489.0 | 40 |
| stele-sweep | D:enriching+keyword+facts | enriching | keyword | facts | hnsw·nb1·k=10 | 0.33 | 0.25 | 288 | 2.1 | 374.3 | 40 |
| stele-sweep | B:keyword+facts | sentence_aware | keyword | facts | hnsw·nb1·k=10 | 0.30 | 0.25 | 288 | 2.2 | 423.6 | 40 |
| letta-agent | (memory) | — | — | — | — | 0.00 | — | — | — | — | 20 |


# Mega grid: sorted by retrieval (coverage view)

Same data as `MEGA-GRID.md`, re-pivoted so you can see which **chunker x retrieval x packing x knobs** combos were actually run. A `·` in the coverage matrix is a combo we never tested.

## Coverage: chunker x retrieval

| chunker \ retrieval | hybrid | cascade_a | cascade_b | keyword | (whole doc) |
|---|---|---|---|---|---|
| sentence_aware | ✓ | ✓ | ✓ | ✓ | ✓ |
| fixed_overlap | ✓ | ✓ | ✓ | ✓ | · |
| consolidation | ✓ | ✓ | ✓ | ✓ | · |
| enriching | ✓ | ✓ | ✓ | ✓ | · |

> The original sweep was a **star design** (vary one axis from the `sentence_aware + hybrid + raw` baseline), so it only ran the L: alternate chunkers with `hybrid`, cascade/keyword with `sentence_aware`. The interaction cells were later filled by `factorial_fill.py` (n=40, the `D:` lanes). **Finding:** no interaction cell beats the baseline. `cascade` ties `hybrid`; the alternate chunkers still lose, or only 'win' by retaining near-whole-doc token counts (e.g. `enriching+cascade_a+facts` hits 0.82 on LoCoMo but at ~26k tokens, which is just `raw_fetch` in disguise). **Caveat:** the `keyword` column is chunker-invariant. After stopword stripping the FTS matches ~1 chunk, which neighbor-expansion pads to a near-constant span, so those cells measure sparse keyword retrieval, not the chunker. The `(whole doc)` column stays sparse by design (`raw_fetch` is chunker-independent).


## locomo

| retrieval | chunker | packing | knobs | jscore | ~tokens | mrr | n | lane |
|---|---|---|---|---|---|---|---|---|
| hybrid | consolidation | digest | hnsw·nb1·k=10 | 0.42 | 1136 | 0.071 | 40 | A:consolidation+digest |
| hybrid | consolidation | facts | hnsw·nb1·k=10 | 0.38 | 1308 | 0.071 | 40 | A:consolidation+facts |
| hybrid | consolidation | raw | hnsw·nb1·k=10 | 0.40 | 304 | 0.071 | 40 | A:consolidation+raw |
| hybrid | enriching | digest | hnsw·nb1·k=10 | 0.40 | 9423 | 0.1 | 40 | A:enriching+digest |
| hybrid | enriching | digest | hnsw·nb1·k=10 | 0.54 | 18786 | 0.208 | 250 | enriching_digest |
| hybrid | enriching | facts | hnsw·nb1·k=10 | 0.40 | 9678 | 0.1 | 40 | A:enriching+facts |
| hybrid | enriching | facts | hnsw·nb1·k=10 | 0.54 | 19108 | 0.208 | 250 | enriching_facts |
| hybrid | enriching | raw | hnsw·nb1·k=10 | 0.38 | 8440 | 0.1 | 40 | A:enriching+raw |
| hybrid | fixed_overlap | digest | hnsw·nb1·k=10 | 0.62 | 3226 | 0.131 | 40 | A:fixed_overlap+digest |
| hybrid | fixed_overlap | facts | hnsw·nb1·k=10 | 0.68 | 3559 | 0.131 | 40 | A:fixed_overlap+facts |
| hybrid | fixed_overlap | raw | hnsw·nb1·k=10 | 0.70 | 4338 | 0.131 | 40 | A:fixed_overlap+raw |
| hybrid | sentence_aware | digest | hnsw·nb1·k=10 | 0.62 | 4225 | 0.138 | 40 | A:sentence_aware+digest |
| hybrid | sentence_aware | digest | hnsw·nb1·k=10 | 0.60 | 4381 | 0.163 | 250 | hybrid_digest_hnsw |
| hybrid | sentence_aware | digest (expanded hints) | hnsw·nb1·k=10 | 0.65 | 4231 | 0.138 | 40 | C:hints-expanded+digest |
| hybrid | sentence_aware | digest (expanded hints) | hnsw·nb1·k=10 | 0.64 | 4306 | 0.156 | 250 | digest_expanded |
| hybrid | sentence_aware | digest (none hints) | hnsw·nb1·k=10 | 0.65 | 4225 | 0.138 | 40 | C:hints-none+digest |
| hybrid | sentence_aware | digest_mix | hnsw·nb1·k=20 | 0.67 | 3773 | 0.151 | 250 | digest_mix |
| hybrid | sentence_aware | facts | hnsw·nb1·k=10 | 0.75 | 4550 | 0.138 | 40 | A:sentence_aware+facts |
| hybrid | sentence_aware | facts | hnsw·nb1·k=10 | 0.64 | 4716 | 0.163 | 250 | hybrid_facts_hnsw |
| hybrid | sentence_aware | facts (expanded hints) | hnsw·nb1·k=10 | 0.65 | 4556 | 0.138 | 40 | C:hints-expanded+facts |
| hybrid | sentence_aware | facts (none hints) | hnsw·nb1·k=10 | 0.72 | 4550 | 0.138 | 40 | C:hints-none+facts |
| hybrid | sentence_aware | raw | exact·nb1·k=10 | 0.71 | 6191 | 0.163 | 250 | hybrid_raw_exact |
| hybrid | sentence_aware | raw | hnsw·nb0·k=1 | 0.38 | 240 | 0.072 | 250 | nb0_k=1 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=10 | 0.63 | 2408 | 0.118 | 250 | nb0_k=10 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=20 | 0.68 | 4738 | 0.12 | 250 | nb0_k=20 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=3 | 0.52 | 724 | 0.103 | 250 | nb0_k=3 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=5 | 0.58 | 1210 | 0.112 | 250 | nb0_k=5 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=1 | 0.43 | 683 | 0.128 | 250 | nb1_k=1 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.68 | 6044 | 0.138 | 40 | A:sentence_aware+raw |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.70 | 6191 | 0.163 | 250 | hybrid_raw_hnsw |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.70 | 7026 | 0.163 | 250 | nb1_k=10 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=20 | 0.74 | 13807 | 0.167 | 250 | nb1_k=20 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=3 | 0.60 | 2076 | 0.151 | 250 | nb1_k=3 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=5 | 0.63 | 3489 | 0.157 | 250 | nb1_k=5 |
| cascade_a | consolidation | digest | hnsw·nb1·k=10 | 0.42 | 1064 | 0.062 | 40 | D:consolidation+cascade_a+digest |
| cascade_a | consolidation | facts | hnsw·nb1·k=10 | 0.38 | 1229 | 0.062 | 40 | D:consolidation+cascade_a+facts |
| cascade_a | consolidation | raw | hnsw·nb1·k=10 | 0.45 | 285 | 0.062 | 40 | D:consolidation+cascade_a+raw |
| cascade_a | enriching | digest | hnsw·nb1·k=10 | 0.72 | 25649 | 0.229 | 40 | D:enriching+cascade_a+digest |
| cascade_a | enriching | facts | hnsw·nb1·k=10 | 0.82 | 26026 | 0.229 | 40 | D:enriching+cascade_a+facts |
| cascade_a | enriching | raw | hnsw·nb1·k=10 | 0.78 | 23895 | 0.229 | 40 | D:enriching+cascade_a+raw |
| cascade_a | fixed_overlap | digest | hnsw·nb1·k=10 | 0.53 | 3364 | 0.12 | 40 | D:fixed_overlap+cascade_a+digest |
| cascade_a | fixed_overlap | facts | hnsw·nb1·k=10 | 0.65 | 3696 | 0.12 | 40 | D:fixed_overlap+cascade_a+facts |
| cascade_a | fixed_overlap | raw | hnsw·nb1·k=10 | 0.62 | 4881 | 0.12 | 40 | D:fixed_overlap+cascade_a+raw |
| cascade_a | sentence_aware | digest | hnsw·nb1·k=10 | 0.57 | 4419 | 0.114 | 40 | B:cascade_a+digest |
| cascade_a | sentence_aware | facts | hnsw·nb1·k=10 | 0.65 | 4763 | 0.114 | 40 | B:cascade_a+facts |
| cascade_a | sentence_aware | raw | hnsw·nb1·k=10 | 0.68 | 7009 | 0.114 | 40 | B:cascade_a+raw |
| cascade_b | consolidation | digest | hnsw·nb1·k=10 | 0.42 | 1206 | 0.048 | 40 | D:consolidation+cascade_b+digest |
| cascade_b | consolidation | facts | hnsw·nb1·k=10 | 0.42 | 1388 | 0.048 | 40 | D:consolidation+cascade_b+facts |
| cascade_b | consolidation | raw | hnsw·nb1·k=10 | 0.45 | 337 | 0.048 | 40 | D:consolidation+cascade_b+raw |
| cascade_b | enriching | digest | hnsw·nb1·k=10 | 0.75 | 25677 | 0.275 | 40 | D:enriching+cascade_b+digest |
| cascade_b | enriching | facts | hnsw·nb1·k=10 | 0.75 | 26056 | 0.275 | 40 | D:enriching+cascade_b+facts |
| cascade_b | enriching | raw | hnsw·nb1·k=10 | 0.75 | 23920 | 0.275 | 40 | D:enriching+cascade_b+raw |
| cascade_b | fixed_overlap | digest | hnsw·nb1·k=10 | 0.65 | 3351 | 0.106 | 40 | D:fixed_overlap+cascade_b+digest |
| cascade_b | fixed_overlap | facts | hnsw·nb1·k=10 | 0.68 | 3685 | 0.106 | 40 | D:fixed_overlap+cascade_b+facts |
| cascade_b | fixed_overlap | raw | hnsw·nb1·k=10 | 0.60 | 4908 | 0.106 | 40 | D:fixed_overlap+cascade_b+raw |
| cascade_b | sentence_aware | digest | hnsw·nb1·k=10 | 0.68 | 4479 | 0.13 | 40 | B:cascade_b+digest |
| cascade_b | sentence_aware | facts | hnsw·nb1·k=10 | 0.75 | 4824 | 0.13 | 40 | B:cascade_b+facts |
| cascade_b | sentence_aware | raw | hnsw·nb1·k=10 | 0.75 | 7020 | 0.13 | 40 | B:cascade_b+raw |
| cascade_b | sentence_aware | raw | hnsw·nb1·k=10 | 0.71 | 7039 | 0.149 | 250 | cascade_b_hnsw |
| keyword | consolidation | digest | hnsw·nb1·k=10 | 0.15 | 228 | 0.05 | 40 | D:consolidation+keyword+digest |
| keyword | consolidation | facts | hnsw·nb1·k=10 | 0.15 | 322 | 0.05 | 40 | D:consolidation+keyword+facts |
| keyword | consolidation | raw | hnsw·nb1·k=10 | 0.15 | 91 | 0.05 | 40 | D:consolidation+keyword+raw |
| keyword | enriching | digest | hnsw·nb1·k=10 | 0.15 | 228 | 0.05 | 40 | D:enriching+keyword+digest |
| keyword | enriching | facts | hnsw·nb1·k=10 | 0.15 | 322 | 0.05 | 40 | D:enriching+keyword+facts |
| keyword | enriching | raw | hnsw·nb1·k=10 | 0.15 | 91 | 0.05 | 40 | D:enriching+keyword+raw |
| keyword | fixed_overlap | digest | hnsw·nb1·k=10 | 0.15 | 228 | 0.05 | 40 | D:fixed_overlap+keyword+digest |
| keyword | fixed_overlap | facts | hnsw·nb1·k=10 | 0.15 | 322 | 0.05 | 40 | D:fixed_overlap+keyword+facts |
| keyword | fixed_overlap | raw | hnsw·nb1·k=10 | 0.15 | 91 | 0.05 | 40 | D:fixed_overlap+keyword+raw |
| keyword | sentence_aware | digest | hnsw·nb1·k=10 | 0.15 | 228 | 0.05 | 40 | B:keyword+digest |
| keyword | sentence_aware | facts | hnsw·nb1·k=10 | 0.15 | 322 | 0.05 | 40 | B:keyword+facts |
| keyword | sentence_aware | raw | hnsw·nb1·k=10 | 0.15 | 91 | 0.05 | 40 | B:keyword+raw |
| keyword | sentence_aware | raw | hnsw·nb1·k=10 | 0.05 | 89 | 0.024 | 250 | keyword |
| (whole doc) | sentence_aware | raw | — | 0.80 | 17869 | 0.275 | 40 | raw_fetch |
| (whole doc) | sentence_aware | raw | — | 0.84 | 19776 | 0.34 | 250 | raw_fetch |

## ragbench-hotpotqa

| retrieval | chunker | packing | knobs | jscore | ~tokens | mrr | n | lane |
|---|---|---|---|---|---|---|---|---|
| hybrid | consolidation | digest | hnsw·nb1·k=10 | 0.72 | 1422 | 0.752 | 40 | A:consolidation+digest |
| hybrid | consolidation | facts | hnsw·nb1·k=10 | 0.75 | 1727 | 0.752 | 40 | A:consolidation+facts |
| hybrid | consolidation | raw | hnsw·nb1·k=10 | 0.78 | 469 | 0.752 | 40 | A:consolidation+raw |
| hybrid | enriching | digest | hnsw·nb1·k=10 | 0.93 | 1622 | 0.875 | 40 | A:enriching+digest |
| hybrid | enriching | digest | hnsw·nb1·k=10 | 0.93 | 1533 | 0.904 | 250 | enriching_digest |
| hybrid | enriching | facts | hnsw·nb1·k=10 | 0.90 | 1985 | 0.875 | 40 | A:enriching+facts |
| hybrid | enriching | facts | hnsw·nb1·k=10 | 0.94 | 1905 | 0.904 | 250 | enriching_facts |
| hybrid | enriching | raw | hnsw·nb1·k=10 | 0.95 | 562 | 0.875 | 40 | A:enriching+raw |
| hybrid | fixed_overlap | digest | hnsw·nb1·k=10 | 0.93 | 1665 | 0.9 | 40 | A:fixed_overlap+digest |
| hybrid | fixed_overlap | facts | hnsw·nb1·k=10 | 0.93 | 2033 | 0.9 | 40 | A:fixed_overlap+facts |
| hybrid | fixed_overlap | raw | hnsw·nb1·k=10 | 0.95 | 579 | 0.9 | 40 | A:fixed_overlap+raw |
| hybrid | sentence_aware | digest | hnsw·nb1·k=10 | 0.95 | 2513 | 0.887 | 40 | A:sentence_aware+digest |
| hybrid | sentence_aware | digest | hnsw·nb1·k=10 | 0.92 | 2235 | 0.889 | 250 | hybrid_digest_hnsw |
| hybrid | sentence_aware | digest (expanded hints) | hnsw·nb1·k=10 | 0.95 | 2513 | 0.887 | 40 | C:hints-expanded+digest |
| hybrid | sentence_aware | digest (expanded hints) | hnsw·nb1·k=10 | 0.92 | 2239 | 0.889 | 250 | digest_expanded |
| hybrid | sentence_aware | digest (none hints) | hnsw·nb1·k=10 | 0.95 | 2513 | 0.887 | 40 | C:hints-none+digest |
| hybrid | sentence_aware | digest_mix | hnsw·nb1·k=20 | 0.92 | 2479 | 0.889 | 250 | digest_mix |
| hybrid | sentence_aware | facts | hnsw·nb1·k=10 | 0.93 | 2884 | 0.887 | 40 | A:sentence_aware+facts |
| hybrid | sentence_aware | facts | hnsw·nb1·k=10 | 0.93 | 2605 | 0.889 | 250 | hybrid_facts_hnsw |
| hybrid | sentence_aware | facts (expanded hints) | hnsw·nb1·k=10 | 0.93 | 2884 | 0.887 | 40 | C:hints-expanded+facts |
| hybrid | sentence_aware | facts (none hints) | hnsw·nb1·k=10 | 0.93 | 2884 | 0.887 | 40 | C:hints-none+facts |
| hybrid | sentence_aware | raw | exact·nb1·k=10 | 0.94 | 1010 | 0.889 | 250 | hybrid_raw_exact |
| hybrid | sentence_aware | raw | hnsw·nb0·k=1 | 0.62 | 186 | 0.78 | 250 | nb0_k=1 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=10 | 0.94 | 498 | 0.823 | 250 | nb0_k=10 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=20 | 0.92 | 498 | 0.823 | 250 | nb0_k=20 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=3 | 0.92 | 450 | 0.821 | 250 | nb0_k=3 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=5 | 0.94 | 495 | 0.823 | 250 | nb0_k=5 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=1 | 0.88 | 398 | 0.876 | 250 | nb1_k=1 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.95 | 1094 | 0.887 | 40 | A:sentence_aware+raw |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.94 | 1010 | 0.889 | 250 | hybrid_raw_hnsw |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.94 | 1010 | 0.889 | 250 | nb1_k=10 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=20 | 0.93 | 1010 | 0.889 | 250 | nb1_k=20 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=3 | 0.94 | 872 | 0.889 | 250 | nb1_k=3 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=5 | 0.94 | 1000 | 0.889 | 250 | nb1_k=5 |
| cascade_a | consolidation | digest | hnsw·nb1·k=10 | 0.75 | 1380 | 0.566 | 40 | D:consolidation+cascade_a+digest |
| cascade_a | consolidation | facts | hnsw·nb1·k=10 | 0.72 | 1674 | 0.566 | 40 | D:consolidation+cascade_a+facts |
| cascade_a | consolidation | raw | hnsw·nb1·k=10 | 0.80 | 453 | 0.566 | 40 | D:consolidation+cascade_a+raw |
| cascade_a | enriching | digest | hnsw·nb1·k=10 | 0.95 | 1667 | 0.9 | 40 | D:enriching+cascade_a+digest |
| cascade_a | enriching | facts | hnsw·nb1·k=10 | 0.93 | 2037 | 0.9 | 40 | D:enriching+cascade_a+facts |
| cascade_a | enriching | raw | hnsw·nb1·k=10 | 0.97 | 579 | 0.9 | 40 | D:enriching+cascade_a+raw |
| cascade_a | fixed_overlap | digest | hnsw·nb1·k=10 | 0.95 | 1665 | 0.875 | 40 | D:fixed_overlap+cascade_a+digest |
| cascade_a | fixed_overlap | facts | hnsw·nb1·k=10 | 0.93 | 2034 | 0.875 | 40 | D:fixed_overlap+cascade_a+facts |
| cascade_a | fixed_overlap | raw | hnsw·nb1·k=10 | 0.95 | 579 | 0.875 | 40 | D:fixed_overlap+cascade_a+raw |
| cascade_a | sentence_aware | digest | hnsw·nb1·k=10 | 0.95 | 2767 | 0.875 | 40 | B:cascade_a+digest |
| cascade_a | sentence_aware | facts | hnsw·nb1·k=10 | 0.95 | 3138 | 0.875 | 40 | B:cascade_a+facts |
| cascade_a | sentence_aware | raw | hnsw·nb1·k=10 | 0.95 | 1228 | 0.875 | 40 | B:cascade_a+raw |
| cascade_b | consolidation | digest | hnsw·nb1·k=10 | 0.65 | 1449 | 0.734 | 40 | D:consolidation+cascade_b+digest |
| cascade_b | consolidation | facts | hnsw·nb1·k=10 | 0.72 | 1749 | 0.734 | 40 | D:consolidation+cascade_b+facts |
| cascade_b | consolidation | raw | hnsw·nb1·k=10 | 0.75 | 472 | 0.734 | 40 | D:consolidation+cascade_b+raw |
| cascade_b | enriching | digest | hnsw·nb1·k=10 | 0.95 | 1667 | 0.9 | 40 | D:enriching+cascade_b+digest |
| cascade_b | enriching | facts | hnsw·nb1·k=10 | 0.93 | 2037 | 0.9 | 40 | D:enriching+cascade_b+facts |
| cascade_b | enriching | raw | hnsw·nb1·k=10 | 0.95 | 579 | 0.9 | 40 | D:enriching+cascade_b+raw |
| cascade_b | fixed_overlap | digest | hnsw·nb1·k=10 | 0.97 | 1665 | 0.9 | 40 | D:fixed_overlap+cascade_b+digest |
| cascade_b | fixed_overlap | facts | hnsw·nb1·k=10 | 0.93 | 2033 | 0.9 | 40 | D:fixed_overlap+cascade_b+facts |
| cascade_b | fixed_overlap | raw | hnsw·nb1·k=10 | 0.97 | 579 | 0.9 | 40 | D:fixed_overlap+cascade_b+raw |
| cascade_b | sentence_aware | digest | hnsw·nb1·k=10 | 0.97 | 2768 | 0.887 | 40 | B:cascade_b+digest |
| cascade_b | sentence_aware | facts | hnsw·nb1·k=10 | 0.95 | 3138 | 0.887 | 40 | B:cascade_b+facts |
| cascade_b | sentence_aware | raw | hnsw·nb1·k=10 | 0.97 | 1228 | 0.887 | 40 | B:cascade_b+raw |
| cascade_b | sentence_aware | raw | hnsw·nb1·k=10 | 0.94 | 1157 | 0.885 | 250 | cascade_b_hnsw |
| keyword | consolidation | digest | hnsw·nb1·k=10 | 0.15 | 194 | 0.2 | 40 | D:consolidation+keyword+digest |
| keyword | consolidation | facts | hnsw·nb1·k=10 | 0.17 | 245 | 0.2 | 40 | D:consolidation+keyword+facts |
| keyword | consolidation | raw | hnsw·nb1·k=10 | 0.15 | 50 | 0.2 | 40 | D:consolidation+keyword+raw |
| keyword | enriching | digest | hnsw·nb1·k=10 | 0.12 | 194 | 0.2 | 40 | D:enriching+keyword+digest |
| keyword | enriching | facts | hnsw·nb1·k=10 | 0.17 | 245 | 0.2 | 40 | D:enriching+keyword+facts |
| keyword | enriching | raw | hnsw·nb1·k=10 | 0.15 | 50 | 0.2 | 40 | D:enriching+keyword+raw |
| keyword | fixed_overlap | digest | hnsw·nb1·k=10 | 0.12 | 194 | 0.2 | 40 | D:fixed_overlap+keyword+digest |
| keyword | fixed_overlap | facts | hnsw·nb1·k=10 | 0.17 | 245 | 0.2 | 40 | D:fixed_overlap+keyword+facts |
| keyword | fixed_overlap | raw | hnsw·nb1·k=10 | 0.15 | 50 | 0.2 | 40 | D:fixed_overlap+keyword+raw |
| keyword | sentence_aware | digest | hnsw·nb1·k=10 | 0.15 | 194 | 0.2 | 40 | B:keyword+digest |
| keyword | sentence_aware | facts | hnsw·nb1·k=10 | 0.17 | 245 | 0.2 | 40 | B:keyword+facts |
| keyword | sentence_aware | raw | hnsw·nb1·k=10 | 0.15 | 50 | 0.2 | 40 | B:keyword+raw |
| keyword | sentence_aware | raw | hnsw·nb1·k=10 | 0.20 | 64 | 0.228 | 250 | keyword |
| (whole doc) | sentence_aware | raw | — | 0.95 | 526 | 0.9 | 40 | raw_fetch |
| (whole doc) | sentence_aware | raw | — | 0.94 | 500 | 0.904 | 250 | raw_fetch |

## ragbench-covidqa

| retrieval | chunker | packing | knobs | jscore | ~tokens | mrr | n | lane |
|---|---|---|---|---|---|---|---|---|
| hybrid | consolidation | digest | hnsw·nb1·k=10 | 0.65 | 1311 | 0.461 | 40 | A:consolidation+digest |
| hybrid | consolidation | facts | hnsw·nb1·k=10 | 0.70 | 1546 | 0.461 | 40 | A:consolidation+facts |
| hybrid | consolidation | raw | hnsw·nb1·k=10 | 0.72 | 490 | 0.461 | 40 | A:consolidation+raw |
| hybrid | enriching | digest | hnsw·nb1·k=10 | 0.75 | 2000 | 0.85 | 40 | A:enriching+digest |
| hybrid | enriching | digest | hnsw·nb1·k=10 | 0.76 | 1939 | 0.882 | 246 | enriching_digest |
| hybrid | enriching | facts | hnsw·nb1·k=10 | 0.75 | 2292 | 0.85 | 40 | A:enriching+facts |
| hybrid | enriching | facts | hnsw·nb1·k=10 | 0.76 | 2242 | 0.882 | 246 | enriching_facts |
| hybrid | enriching | raw | hnsw·nb1·k=10 | 0.72 | 658 | 0.85 | 40 | A:enriching+raw |
| hybrid | fixed_overlap | digest | hnsw·nb1·k=10 | 0.75 | 1999 | 0.85 | 40 | A:fixed_overlap+digest |
| hybrid | fixed_overlap | facts | hnsw·nb1·k=10 | 0.75 | 2289 | 0.85 | 40 | A:fixed_overlap+facts |
| hybrid | fixed_overlap | raw | hnsw·nb1·k=10 | 0.70 | 657 | 0.85 | 40 | A:fixed_overlap+raw |
| hybrid | sentence_aware | digest | hnsw·nb1·k=10 | 0.70 | 2873 | 0.825 | 40 | A:sentence_aware+digest |
| hybrid | sentence_aware | digest | hnsw·nb1·k=10 | 0.77 | 2839 | 0.841 | 246 | hybrid_digest_hnsw |
| hybrid | sentence_aware | digest (expanded hints) | hnsw·nb1·k=10 | 0.72 | 2873 | 0.825 | 40 | C:hints-expanded+digest |
| hybrid | sentence_aware | digest (expanded hints) | hnsw·nb1·k=10 | 0.78 | 2841 | 0.841 | 246 | digest_expanded |
| hybrid | sentence_aware | digest (none hints) | hnsw·nb1·k=10 | 0.68 | 2873 | 0.825 | 40 | C:hints-none+digest |
| hybrid | sentence_aware | digest_mix | hnsw·nb1·k=20 | 0.77 | 2935 | 0.84 | 246 | digest_mix |
| hybrid | sentence_aware | facts | hnsw·nb1·k=10 | 0.72 | 3178 | 0.825 | 40 | A:sentence_aware+facts |
| hybrid | sentence_aware | facts | hnsw·nb1·k=10 | 0.76 | 3159 | 0.841 | 246 | hybrid_facts_hnsw |
| hybrid | sentence_aware | facts (expanded hints) | hnsw·nb1·k=10 | 0.72 | 3178 | 0.825 | 40 | C:hints-expanded+facts |
| hybrid | sentence_aware | facts (none hints) | hnsw·nb1·k=10 | 0.68 | 3178 | 0.825 | 40 | C:hints-none+facts |
| hybrid | sentence_aware | raw | exact·nb1·k=10 | 0.78 | 1368 | 0.841 | 246 | hybrid_raw_exact |
| hybrid | sentence_aware | raw | hnsw·nb0·k=1 | 0.63 | 179 | 0.593 | 246 | nb0_k=1 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=10 | 0.75 | 563 | 0.677 | 246 | nb0_k=10 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=20 | 0.75 | 563 | 0.677 | 246 | nb0_k=20 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=3 | 0.74 | 477 | 0.672 | 246 | nb0_k=3 |
| hybrid | sentence_aware | raw | hnsw·nb0·k=5 | 0.74 | 563 | 0.677 | 246 | nb0_k=5 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=1 | 0.72 | 388 | 0.813 | 246 | nb1_k=1 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.72 | 1309 | 0.825 | 40 | A:sentence_aware+raw |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.78 | 1368 | 0.841 | 246 | hybrid_raw_hnsw |
| hybrid | sentence_aware | raw | hnsw·nb1·k=10 | 0.77 | 1368 | 0.841 | 246 | nb1_k=10 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=20 | 0.77 | 1368 | 0.841 | 246 | nb1_k=20 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=3 | 0.76 | 1144 | 0.84 | 246 | nb1_k=3 |
| hybrid | sentence_aware | raw | hnsw·nb1·k=5 | 0.77 | 1368 | 0.841 | 246 | nb1_k=5 |
| cascade_a | consolidation | digest | hnsw·nb1·k=10 | 0.70 | 1192 | 0.397 | 40 | D:consolidation+cascade_a+digest |
| cascade_a | consolidation | facts | hnsw·nb1·k=10 | 0.68 | 1405 | 0.397 | 40 | D:consolidation+cascade_a+facts |
| cascade_a | consolidation | raw | hnsw·nb1·k=10 | 0.65 | 407 | 0.397 | 40 | D:consolidation+cascade_a+raw |
| cascade_a | enriching | digest | hnsw·nb1·k=10 | 0.80 | 2000 | 0.85 | 40 | D:enriching+cascade_a+digest |
| cascade_a | enriching | facts | hnsw·nb1·k=10 | 0.75 | 2292 | 0.85 | 40 | D:enriching+cascade_a+facts |
| cascade_a | enriching | raw | hnsw·nb1·k=10 | 0.72 | 658 | 0.85 | 40 | D:enriching+cascade_a+raw |
| cascade_a | fixed_overlap | digest | hnsw·nb1·k=10 | 0.78 | 1984 | 0.838 | 40 | D:fixed_overlap+cascade_a+digest |
| cascade_a | fixed_overlap | facts | hnsw·nb1·k=10 | 0.78 | 2274 | 0.838 | 40 | D:fixed_overlap+cascade_a+facts |
| cascade_a | fixed_overlap | raw | hnsw·nb1·k=10 | 0.75 | 648 | 0.838 | 40 | D:fixed_overlap+cascade_a+raw |
| cascade_a | sentence_aware | digest | hnsw·nb1·k=10 | 0.72 | 2923 | 0.812 | 40 | B:cascade_a+digest |
| cascade_a | sentence_aware | facts | hnsw·nb1·k=10 | 0.72 | 3226 | 0.812 | 40 | B:cascade_a+facts |
| cascade_a | sentence_aware | raw | hnsw·nb1·k=10 | 0.72 | 1350 | 0.812 | 40 | B:cascade_a+raw |
| cascade_b | consolidation | digest | hnsw·nb1·k=10 | 0.68 | 1315 | 0.447 | 40 | D:consolidation+cascade_b+digest |
| cascade_b | consolidation | facts | hnsw·nb1·k=10 | 0.65 | 1545 | 0.447 | 40 | D:consolidation+cascade_b+facts |
| cascade_b | consolidation | raw | hnsw·nb1·k=10 | 0.70 | 493 | 0.447 | 40 | D:consolidation+cascade_b+raw |
| cascade_b | enriching | digest | hnsw·nb1·k=10 | 0.78 | 2000 | 0.85 | 40 | D:enriching+cascade_b+digest |
| cascade_b | enriching | facts | hnsw·nb1·k=10 | 0.72 | 2292 | 0.85 | 40 | D:enriching+cascade_b+facts |
| cascade_b | enriching | raw | hnsw·nb1·k=10 | 0.70 | 658 | 0.85 | 40 | D:enriching+cascade_b+raw |
| cascade_b | fixed_overlap | digest | hnsw·nb1·k=10 | 0.78 | 1999 | 0.85 | 40 | D:fixed_overlap+cascade_b+digest |
| cascade_b | fixed_overlap | facts | hnsw·nb1·k=10 | 0.75 | 2290 | 0.85 | 40 | D:fixed_overlap+cascade_b+facts |
| cascade_b | fixed_overlap | raw | hnsw·nb1·k=10 | 0.70 | 658 | 0.85 | 40 | D:fixed_overlap+cascade_b+raw |
| cascade_b | sentence_aware | digest | hnsw·nb1·k=10 | 0.72 | 2925 | 0.812 | 40 | B:cascade_b+digest |
| cascade_b | sentence_aware | facts | hnsw·nb1·k=10 | 0.68 | 3232 | 0.812 | 40 | B:cascade_b+facts |
| cascade_b | sentence_aware | raw | hnsw·nb1·k=10 | 0.72 | 1350 | 0.812 | 40 | B:cascade_b+raw |
| cascade_b | sentence_aware | raw | hnsw·nb1·k=10 | 0.77 | 1399 | 0.842 | 246 | cascade_b_hnsw |
| keyword | consolidation | digest | hnsw·nb1·k=10 | 0.35 | 233 | 0.25 | 40 | D:consolidation+keyword+digest |
| keyword | consolidation | facts | hnsw·nb1·k=10 | 0.35 | 288 | 0.25 | 40 | D:consolidation+keyword+facts |
| keyword | consolidation | raw | hnsw·nb1·k=10 | 0.35 | 55 | 0.25 | 40 | D:consolidation+keyword+raw |
| keyword | enriching | digest | hnsw·nb1·k=10 | 0.35 | 233 | 0.25 | 40 | D:enriching+keyword+digest |
| keyword | enriching | facts | hnsw·nb1·k=10 | 0.33 | 288 | 0.25 | 40 | D:enriching+keyword+facts |
| keyword | enriching | raw | hnsw·nb1·k=10 | 0.35 | 55 | 0.25 | 40 | D:enriching+keyword+raw |
| keyword | fixed_overlap | digest | hnsw·nb1·k=10 | 0.35 | 233 | 0.25 | 40 | D:fixed_overlap+keyword+digest |
| keyword | fixed_overlap | facts | hnsw·nb1·k=10 | 0.35 | 288 | 0.25 | 40 | D:fixed_overlap+keyword+facts |
| keyword | fixed_overlap | raw | hnsw·nb1·k=10 | 0.35 | 55 | 0.25 | 40 | D:fixed_overlap+keyword+raw |
| keyword | sentence_aware | digest | hnsw·nb1·k=10 | 0.33 | 233 | 0.25 | 40 | B:keyword+digest |
| keyword | sentence_aware | facts | hnsw·nb1·k=10 | 0.30 | 288 | 0.25 | 40 | B:keyword+facts |
| keyword | sentence_aware | raw | hnsw·nb1·k=10 | 0.33 | 55 | 0.25 | 40 | B:keyword+raw |
| keyword | sentence_aware | raw | hnsw·nb1·k=10 | 0.35 | 50 | 0.232 | 246 | keyword |
| (whole doc) | sentence_aware | raw | — | 0.72 | 568 | 0.85 | 40 | raw_fetch |
| (whole doc) | sentence_aware | raw | — | 0.75 | 580 | 0.882 | 246 | raw_fetch |

# Mega benchmark grid — every lane x corpus (post-fix)

jscore = Mem0 jscore (gemma@133, abstention=wrong) · mrr = recip. rank of first chunk with gold (stele only; competitor memories are abstractive) · tokens ≈ ctx_chars/4 · retr/ans_ms = latency.


## locomo

| system | lane | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|
| stele-highN | raw_fetch | 0.84 | 0.34 | 19776 | 0.0 | 2135.2 | 250 |
| stele-sweep | raw_fetch | 0.80 | 0.275 | 17869 | 0.0 | 1740.7 | 40 |
| stele-sweep | A:sentence_aware+facts | 0.75 | 0.138 | 4550 | 33.9 | 989.8 | 40 |
| stele-sweep | B:cascade_b+raw | 0.75 | 0.13 | 7020 | 62.6 | 2420.3 | 40 |
| stele-sweep | B:cascade_b+facts | 0.75 | 0.13 | 4824 | 62.6 | 832.8 | 40 |
| stele-highN | nb1_k=20 | 0.74 | 0.167 | 13807 | 57.3 | 3128.6 | 250 |
| stele-sweep | C:hints-none+facts | 0.72 | 0.138 | 4550 | 33.9 | 865.3 | 40 |
| stele-highN | cascade_b_hnsw | 0.71 | 0.149 | 7039 | 64.9 | 2874.9 | 250 |
| stele-highN | hybrid_raw_exact | 0.71 | 0.163 | 6191 | 33.5 | 1168.2 | 250 |
| stele-highN | hybrid_raw_hnsw | 0.70 | 0.163 | 6191 | 32.8 | 2680.4 | 250 |
| stele-sweep | A:fixed_overlap+raw | 0.70 | 0.131 | 4338 | 28.9 | 1577.2 | 40 |
| stele-highN | nb1_k=10 | 0.70 | 0.163 | 7026 | 57.3 | 1904.6 | 250 |
| stele-highN | nb0_k=20 | 0.68 | 0.12 | 4738 | 53.9 | 1682.5 | 250 |
| stele-sweep | A:fixed_overlap+facts | 0.68 | 0.131 | 3559 | 28.9 | 765.8 | 40 |
| stele-sweep | A:sentence_aware+raw | 0.68 | 0.138 | 6044 | 33.9 | 1997.2 | 40 |
| stele-sweep | B:cascade_a+raw | 0.68 | 0.114 | 7009 | 62.8 | 2481.6 | 40 |
| stele-sweep | B:cascade_b+digest | 0.68 | 0.13 | 4479 | 62.6 | 1733.5 | 40 |
| stele-highN | digest_mix | 0.67 | 0.151 | 3773 | 57.3 | 2003.7 | 250 |
| stele-sweep | B:cascade_a+facts | 0.65 | 0.114 | 4763 | 62.8 | 892.3 | 40 |
| stele-sweep | C:hints-none+digest | 0.65 | 0.138 | 4225 | 33.9 | 668.2 | 40 |
| stele-sweep | C:hints-expanded+digest | 0.65 | 0.138 | 4231 | 33.9 | 1789.6 | 40 |
| stele-sweep | C:hints-expanded+facts | 0.65 | 0.138 | 4556 | 33.9 | 836.0 | 40 |
| stele-highN | hybrid_facts_hnsw | 0.64 | 0.163 | 4716 | 32.8 | 2330.2 | 250 |
| stele-highN | digest_expanded | 0.64 | 0.156 | 4306 | 29.1 | 2013.6 | 250 |
| stele-highN | nb1_k=5 | 0.63 | 0.157 | 3489 | 57.3 | 1128.2 | 250 |
| stele-highN | nb0_k=10 | 0.63 | 0.118 | 2408 | 53.9 | 1081.6 | 250 |
| stele-sweep | A:fixed_overlap+digest | 0.62 | 0.131 | 3226 | 28.9 | 1303.9 | 40 |
| stele-sweep | A:sentence_aware+digest | 0.62 | 0.138 | 4225 | 33.9 | 1802.1 | 40 |
| stele-highN | nb1_k=3 | 0.60 | 0.151 | 2076 | 57.3 | 894.6 | 250 |
| stele-highN | hybrid_digest_hnsw | 0.60 | 0.163 | 4381 | 52.0 | 3071.5 | 250 |
| stele-highN | nb0_k=5 | 0.58 | 0.112 | 1210 | 53.9 | 760.9 | 250 |
| stele-sweep | B:cascade_a+digest | 0.57 | 0.114 | 4419 | 62.8 | 1995.9 | 40 |
| letta-archival | (memory) | 0.56 | — | 1757 | 407.3 | 2117.9 | 250 |
| stele-highN | enriching_digest | 0.54 | 0.208 | 18786 | 26.8 | 2635.8 | 250 |
| stele-highN | enriching_facts | 0.54 | 0.208 | 19108 | 26.8 | 1415.3 | 250 |
| stele-highN | nb0_k=3 | 0.52 | 0.103 | 724 | 53.9 | 627.9 | 250 |
| stele-highN | nb1_k=1 | 0.43 | 0.128 | 683 | 57.3 | 489.6 | 250 |
| stele-sweep | A:consolidation+digest | 0.42 | 0.071 | 1136 | 26.5 | 881.8 | 40 |
| stele-sweep | A:consolidation+raw | 0.40 | 0.071 | 304 | 26.5 | 488.4 | 40 |
| stele-sweep | A:enriching+digest | 0.40 | 0.1 | 9423 | 28.3 | 2246.4 | 40 |
| stele-sweep | A:enriching+facts | 0.40 | 0.1 | 9678 | 28.3 | 1014.9 | 40 |
| stele-highN | nb0_k=1 | 0.38 | 0.072 | 240 | 53.9 | 325.8 | 250 |
| stele-sweep | A:consolidation+facts | 0.38 | 0.071 | 1308 | 26.5 | 585.7 | 40 |
| stele-sweep | A:enriching+raw | 0.38 | 0.1 | 8440 | 28.3 | 1429.4 | 40 |
| stele-sweep | B:keyword+raw | 0.15 | 0.05 | 91 | 13.9 | 252.3 | 40 |
| stele-sweep | B:keyword+digest | 0.15 | 0.05 | 228 | 13.9 | 291.9 | 40 |
| stele-sweep | B:keyword+facts | 0.15 | 0.05 | 322 | 13.9 | 224.6 | 40 |
| mem0-local | (memory) | 0.11 | — | 462 | 122.6 | 951.5 | 250 |
| stele-highN | keyword | 0.05 | 0.024 | 89 | 14.9 | 274.5 | 250 |
| PARAMETRIC-FLOOR | (no context) | 0.00 | — | 0 | — | — | 250 |
| letta-agent | (memory) | 0.00 | — | — | — | — | 20 |

## ragbench-hotpotqa

| system | lane | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|
| stele-sweep | B:cascade_b+raw | 0.97 | 0.887 | 1228 | 52.6 | 558.8 | 40 |
| stele-sweep | B:cascade_b+digest | 0.97 | 0.887 | 2768 | 52.6 | 578.4 | 40 |
| stele-sweep | A:fixed_overlap+raw | 0.95 | 0.9 | 579 | 62.5 | 593.1 | 40 |
| stele-sweep | A:sentence_aware+raw | 0.95 | 0.887 | 1094 | 24.4 | 702.0 | 40 |
| stele-sweep | A:sentence_aware+digest | 0.95 | 0.887 | 2513 | 24.4 | 1033.0 | 40 |
| stele-sweep | A:enriching+raw | 0.95 | 0.875 | 562 | 26.9 | 572.5 | 40 |
| stele-sweep | B:cascade_a+raw | 0.95 | 0.875 | 1228 | 53.4 | 711.3 | 40 |
| stele-sweep | B:cascade_a+digest | 0.95 | 0.875 | 2767 | 53.4 | 985.6 | 40 |
| stele-sweep | B:cascade_a+facts | 0.95 | 0.875 | 3138 | 53.4 | 622.9 | 40 |
| stele-sweep | B:cascade_b+facts | 0.95 | 0.887 | 3138 | 52.6 | 502.5 | 40 |
| stele-sweep | C:hints-none+digest | 0.95 | 0.887 | 2513 | 24.4 | 491.4 | 40 |
| stele-sweep | C:hints-expanded+digest | 0.95 | 0.887 | 2513 | 24.4 | 1026.9 | 40 |
| stele-sweep | raw_fetch | 0.95 | 0.9 | 526 | 0.0 | 676.8 | 40 |
| stele-highN | cascade_b_hnsw | 0.94 | 0.885 | 1157 | 48.9 | 564.0 | 250 |
| stele-highN | nb0_k=10 | 0.94 | 0.823 | 498 | 28.0 | 418.7 | 250 |
| stele-highN | raw_fetch | 0.94 | 0.904 | 500 | 0.0 | 517.5 | 250 |
| stele-highN | hybrid_raw_exact | 0.94 | 0.889 | 1010 | 27.0 | 444.1 | 250 |
| stele-highN | nb1_k=5 | 0.94 | 0.889 | 1000 | 39.6 | 508.9 | 250 |
| stele-highN | hybrid_raw_hnsw | 0.94 | 0.889 | 1010 | 26.2 | 622.6 | 250 |
| stele-highN | enriching_facts | 0.94 | 0.904 | 1905 | 22.1 | 530.2 | 250 |
| stele-highN | nb1_k=3 | 0.94 | 0.889 | 872 | 39.6 | 579.4 | 250 |
| stele-highN | nb1_k=10 | 0.94 | 0.889 | 1010 | 39.6 | 433.0 | 250 |
| stele-highN | nb0_k=5 | 0.94 | 0.823 | 495 | 28.0 | 448.7 | 250 |
| stele-highN | nb1_k=20 | 0.93 | 0.889 | 1010 | 39.6 | 441.6 | 250 |
| stele-highN | hybrid_facts_hnsw | 0.93 | 0.889 | 2605 | 26.2 | 1076.3 | 250 |
| stele-highN | enriching_digest | 0.93 | 0.904 | 1533 | 22.1 | 786.7 | 250 |
| stele-sweep | A:fixed_overlap+digest | 0.93 | 0.9 | 1665 | 62.5 | 848.8 | 40 |
| stele-sweep | A:fixed_overlap+facts | 0.93 | 0.9 | 2033 | 62.5 | 637.9 | 40 |
| stele-sweep | A:sentence_aware+facts | 0.93 | 0.887 | 2884 | 24.4 | 636.0 | 40 |
| stele-sweep | A:enriching+digest | 0.93 | 0.875 | 1622 | 26.9 | 742.4 | 40 |
| stele-sweep | C:hints-none+facts | 0.93 | 0.887 | 2884 | 24.4 | 487.2 | 40 |
| stele-sweep | C:hints-expanded+facts | 0.93 | 0.887 | 2884 | 24.4 | 604.9 | 40 |
| stele-highN | hybrid_digest_hnsw | 0.92 | 0.889 | 2235 | 38.8 | 1613.2 | 250 |
| stele-highN | nb0_k=20 | 0.92 | 0.823 | 498 | 28.0 | 420.6 | 250 |
| stele-highN | digest_expanded | 0.92 | 0.889 | 2239 | 34.4 | 969.4 | 250 |
| stele-highN | nb0_k=3 | 0.92 | 0.821 | 450 | 28.0 | 468.3 | 250 |
| letta-archival | (memory) | 0.92 | — | 500 | 368.0 | 977.2 | 250 |
| stele-highN | digest_mix | 0.92 | 0.889 | 2479 | 39.6 | 1038.2 | 250 |
| stele-sweep | A:enriching+facts | 0.90 | 0.875 | 1985 | 26.9 | 542.6 | 40 |
| stele-highN | nb1_k=1 | 0.88 | 0.876 | 398 | 39.6 | 445.6 | 250 |
| stele-sweep | A:consolidation+raw | 0.78 | 0.752 | 469 | 26.6 | 545.4 | 40 |
| stele-sweep | A:consolidation+facts | 0.75 | 0.752 | 1727 | 26.6 | 553.9 | 40 |
| stele-sweep | A:consolidation+digest | 0.72 | 0.752 | 1422 | 26.6 | 745.3 | 40 |
| stele-highN | nb0_k=1 | 0.62 | 0.78 | 186 | 28.0 | 357.3 | 250 |
| mem0-local | (memory) | 0.44 | — | 139 | 155.2 | 700.5 | 250 |
| stele-highN | keyword | 0.20 | 0.228 | 64 | 2.1 | 244.6 | 250 |
| stele-sweep | B:keyword+facts | 0.17 | 0.2 | 245 | 2.1 | 310.9 | 40 |
| stele-sweep | B:keyword+raw | 0.15 | 0.2 | 50 | 2.1 | 230.4 | 40 |
| stele-sweep | B:keyword+digest | 0.15 | 0.2 | 194 | 2.1 | 312.1 | 40 |
| PARAMETRIC-FLOOR | (no context) | 0.02 | — | 0 | — | — | 250 |
| letta-agent | (memory) | 0.00 | — | — | — | — | 20 |

## ragbench-covidqa

| system | lane | jscore | mrr | ~tokens | retr_ms | ans_ms | n |
|---|---|---|---|---|---|---|---|
| stele-highN | hybrid_raw_hnsw | 0.78 | 0.841 | 1368 | 25.6 | 1122.8 | 246 |
| stele-highN | digest_expanded | 0.78 | 0.841 | 2841 | 46.4 | 1525.9 | 246 |
| stele-highN | hybrid_raw_exact | 0.78 | 0.841 | 1368 | 26.5 | 880.1 | 246 |
| stele-highN | cascade_b_hnsw | 0.77 | 0.842 | 1399 | 48.8 | 1016.2 | 246 |
| stele-highN | nb1_k=5 | 0.77 | 0.841 | 1368 | 36.8 | 936.7 | 246 |
| stele-highN | digest_mix | 0.77 | 0.84 | 2935 | 36.8 | 1518.8 | 246 |
| stele-highN | hybrid_digest_hnsw | 0.77 | 0.841 | 2839 | 39.1 | 2832.6 | 246 |
| stele-highN | nb1_k=10 | 0.77 | 0.841 | 1368 | 36.8 | 884.7 | 246 |
| stele-highN | nb1_k=20 | 0.77 | 0.841 | 1368 | 36.8 | 874.9 | 246 |
| stele-highN | enriching_digest | 0.76 | 0.882 | 1939 | 32.8 | 1293.7 | 246 |
| stele-highN | enriching_facts | 0.76 | 0.882 | 2242 | 32.8 | 1020.0 | 246 |
| stele-highN | nb1_k=3 | 0.76 | 0.84 | 1144 | 36.8 | 1051.9 | 246 |
| stele-highN | hybrid_facts_hnsw | 0.76 | 0.841 | 3159 | 25.6 | 1561.8 | 246 |
| stele-highN | raw_fetch | 0.75 | 0.882 | 580 | 0.0 | 882.4 | 246 |
| stele-highN | nb0_k=10 | 0.75 | 0.677 | 563 | 27.6 | 787.0 | 246 |
| stele-sweep | A:fixed_overlap+digest | 0.75 | 0.85 | 1999 | 43.0 | 1211.2 | 40 |
| stele-sweep | A:fixed_overlap+facts | 0.75 | 0.85 | 2289 | 43.0 | 952.3 | 40 |
| stele-sweep | A:enriching+digest | 0.75 | 0.85 | 2000 | 31.3 | 1212.5 | 40 |
| stele-sweep | A:enriching+facts | 0.75 | 0.85 | 2292 | 31.3 | 1026.9 | 40 |
| stele-highN | nb0_k=20 | 0.75 | 0.677 | 563 | 27.6 | 752.7 | 246 |
| letta-archival | (memory) | 0.74 | — | 580 | 452.9 | 1581.7 | 246 |
| stele-highN | nb0_k=5 | 0.74 | 0.677 | 563 | 27.6 | 827.9 | 246 |
| stele-highN | nb0_k=3 | 0.74 | 0.672 | 477 | 27.6 | 797.0 | 246 |
| stele-sweep | A:sentence_aware+raw | 0.72 | 0.825 | 1309 | 31.4 | 1096.2 | 40 |
| stele-sweep | A:sentence_aware+facts | 0.72 | 0.825 | 3178 | 31.4 | 921.7 | 40 |
| stele-sweep | A:consolidation+raw | 0.72 | 0.461 | 490 | 32.9 | 793.2 | 40 |
| stele-sweep | A:enriching+raw | 0.72 | 0.85 | 658 | 31.3 | 846.7 | 40 |
| stele-sweep | B:cascade_a+raw | 0.72 | 0.812 | 1350 | 53.8 | 995.5 | 40 |
| stele-sweep | B:cascade_a+digest | 0.72 | 0.812 | 2923 | 53.8 | 1273.9 | 40 |
| stele-sweep | B:cascade_a+facts | 0.72 | 0.812 | 3226 | 53.8 | 941.3 | 40 |
| stele-sweep | B:cascade_b+raw | 0.72 | 0.812 | 1350 | 49.9 | 860.2 | 40 |
| stele-sweep | B:cascade_b+digest | 0.72 | 0.812 | 2925 | 49.9 | 1039.3 | 40 |
| stele-sweep | C:hints-expanded+digest | 0.72 | 0.825 | 2873 | 31.4 | 1375.8 | 40 |
| stele-sweep | C:hints-expanded+facts | 0.72 | 0.825 | 3178 | 31.4 | 998.8 | 40 |
| stele-sweep | raw_fetch | 0.72 | 0.85 | 568 | 0.0 | 882.6 | 40 |
| stele-highN | nb1_k=1 | 0.72 | 0.813 | 388 | 36.8 | 746.0 | 246 |
| stele-sweep | A:fixed_overlap+raw | 0.70 | 0.85 | 657 | 43.0 | 919.3 | 40 |
| stele-sweep | A:sentence_aware+digest | 0.70 | 0.825 | 2873 | 31.4 | 1474.7 | 40 |
| stele-sweep | A:consolidation+facts | 0.70 | 0.461 | 1546 | 32.9 | 745.2 | 40 |
| stele-sweep | B:cascade_b+facts | 0.68 | 0.812 | 3232 | 49.9 | 820.3 | 40 |
| stele-sweep | C:hints-none+digest | 0.68 | 0.825 | 2873 | 31.4 | 824.7 | 40 |
| stele-sweep | C:hints-none+facts | 0.68 | 0.825 | 3178 | 31.4 | 724.2 | 40 |
| stele-sweep | A:consolidation+digest | 0.65 | 0.461 | 1311 | 32.9 | 926.2 | 40 |
| stele-highN | nb0_k=1 | 0.63 | 0.593 | 179 | 27.6 | 529.1 | 246 |
| stele-highN | keyword | 0.35 | 0.232 | 50 | 2.1 | 314.5 | 246 |
| stele-sweep | B:keyword+raw | 0.33 | 0.25 | 55 | 2.2 | 353.6 | 40 |
| stele-sweep | B:keyword+digest | 0.33 | 0.25 | 233 | 2.2 | 489.0 | 40 |
| stele-sweep | B:keyword+facts | 0.30 | 0.25 | 288 | 2.2 | 423.6 | 40 |
| mem0-local | (memory) | 0.14 | — | 26 | 70.6 | 507.5 | 246 |
| PARAMETRIC-FLOOR | (no context) | 0.04 | — | 0 | — | — | 246 |
| letta-agent | (memory) | 0.00 | — | — | — | — | 20 |

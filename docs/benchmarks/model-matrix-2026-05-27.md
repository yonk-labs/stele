# Model matrix — Mem0 vs stele across answerers (judge held constant)

Generated `2026-05-27T04:16:56.176429+00:00` · root `benchmarks/runs/matrix-20260527T023026Z`

**Judge = gpt-4o for every row**, so differences are *answerer* effects, not judge effects. Packing: `search_first`=raw chunks, `digest`=lede summary+facts+top-5, `raw_fetch`=full context. Small N (LoCoMo 18, LongMemEval 12) — read as directional.

**Versions**: chunkshop `0.6.1`  ·  lede `0.4.5`  ·  pg-raggraph `0.4.0a1`  ·  stele-core `0.2.1`

## locomo: does the summary help or hurt, per answerer?

| answerer | search_first (raw) | digest (summary) | raw_fetch (full) | digest − search_first |
| --- | ---: | ---: | ---: | ---: |
| qwen | 0.500 | 0.389 | 0.278 | -0.111 |
| gemma | 0.500 | 0.667 | 0.833 | +0.167 |
| gpt-4o | 0.389 | 0.556 | 0.556 | +0.167 |
| gpt-5-mini | 0.444 | 0.389 | 0.389 | -0.055 |
| gpt-5 | 0.333 | 0.389 | 0.667 | +0.056 |
| gpt-4-turbo | 0.444 | 0.444 | 0.500 | +0.000 |

## longmemeval: does the summary help or hurt, per answerer?

| answerer | search_first (raw) | digest (summary) | raw_fetch (full) | digest − search_first |
| --- | ---: | ---: | ---: | ---: |
| qwen | 0.833 | 0.750 | 0.750 | -0.083 |
| gemma | 0.833 | 0.750 | 0.833 | -0.083 |
| gpt-4o | 0.833 | 0.750 | 0.667 | -0.083 |
| gpt-5-mini | 0.750 | 0.833 | 0.750 | +0.083 |
| gpt-5 | 0.833 | 0.833 | 0.833 | +0.000 |
| gpt-4-turbo | 0.833 | 0.833 | 0.667 | +0.000 |

## Does block order matter? (digest variants)

S=summary, F=facts, C=chunks. `digest`=SFC (default).

| answerer | dataset | SFC | FCS | CSF | CFS |
| --- | --- | ---: | ---: | ---: | ---: |
| qwen | locomo | 0.389 | 0.389 | 0.389 | 0.444 |
| qwen | longmemeval | 0.750 | 0.750 | 0.750 | 0.750 |
| gpt-4o | locomo | 0.556 | 0.500 | 0.500 | 0.500 |
| gpt-4o | longmemeval | 0.750 | 0.750 | 0.750 | 0.833 |
| gpt-5-mini | locomo | 0.389 | 0.389 | 0.389 | 0.500 |
| gpt-5-mini | longmemeval | 0.833 | 0.750 | 0.833 | 0.833 |

## Mem0 vs stele (LoCoMo, same answerer + gpt-4o judge)

| answerer | Mem0 | stele search_first | stele digest | stele raw_fetch | Mem0 mean_tok | Mem0 search_ms | Mem0 ingest_s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen | 0.722 | 0.500 | 0.389 | 0.278 | 540.3 | 260.0 | 245.2 |
| gemma | 0.556 | 0.500 | 0.667 | 0.833 | 546.3 | 329.0 | 192.1 |
| gpt-4o | 0.667 | 0.389 | 0.556 | 0.556 | 540.5 | 309.8 | 224.3 |
| gpt-5-mini | 0.667 | 0.444 | 0.389 | 0.389 | 550.6 | 248.7 | 298.3 |
| gpt-5 | 0.611 | 0.333 | 0.389 | 0.667 | 535.3 | 292.1 | 244.9 |
| gpt-4 | 0.667 | - | - | - | 557.7 | 189.5 | 230.4 |

## Full grid (accuracy @ mean tokens)

| answerer | dataset | strategy | acc | tok |
| --- | --- | --- | ---: | ---: |
| gemma | locomo | adaptive | 0.500 | 4357 |
| gemma | locomo | digest | 0.667 | 1198 |
| gemma | locomo | raw_fetch | 0.833 | 10412 |
| gemma | locomo | search_first | 0.500 | 106 |
| gemma | longmemeval | adaptive | 0.750 | 11670 |
| gemma | longmemeval | digest | 0.750 | 1219 |
| gemma | longmemeval | raw_fetch | 0.833 | 15389 |
| gemma | longmemeval | search_first | 0.833 | 60 |
| gpt-4-turbo | locomo | adaptive | 0.389 | 4383 |
| gpt-4-turbo | locomo | digest | 0.444 | 1219 |
| gpt-4-turbo | locomo | raw_fetch | 0.500 | 10413 |
| gpt-4-turbo | locomo | search_first | 0.444 | 106 |
| gpt-4-turbo | longmemeval | adaptive | 0.583 | 11754 |
| gpt-4-turbo | longmemeval | digest | 0.833 | 1206 |
| gpt-4-turbo | longmemeval | raw_fetch | 0.667 | 15484 |
| gpt-4-turbo | longmemeval | search_first | 0.833 | 60 |
| gpt-4o | locomo | adaptive | 0.556 | 4347 |
| gpt-4o | locomo | digest | 0.556 | 1198 |
| gpt-4o | locomo | digest_cfs | 0.500 | 1205 |
| gpt-4o | locomo | digest_csf | 0.500 | 1203 |
| gpt-4o | locomo | digest_fcs | 0.500 | 1202 |
| gpt-4o | locomo | raw_fetch | 0.556 | 10382 |
| gpt-4o | locomo | search_first | 0.389 | 105 |
| gpt-4o | longmemeval | adaptive | 0.833 | 11668 |
| gpt-4o | longmemeval | digest | 0.750 | 1206 |
| gpt-4o | longmemeval | digest_cfs | 0.833 | 1207 |
| gpt-4o | longmemeval | digest_csf | 0.750 | 1208 |
| gpt-4o | longmemeval | digest_fcs | 0.750 | 1207 |
| gpt-4o | longmemeval | raw_fetch | 0.667 | 15388 |
| gpt-4o | longmemeval | search_first | 0.833 | 60 |
| gpt-5 | locomo | adaptive | 0.389 | 4350 |
| gpt-5 | locomo | digest | 0.389 | 1196 |
| gpt-5 | locomo | raw_fetch | 0.667 | 10385 |
| gpt-5 | locomo | search_first | 0.333 | 105 |
| gpt-5 | longmemeval | adaptive | 0.750 | 11668 |
| gpt-5 | longmemeval | digest | 0.833 | 1204 |
| gpt-5 | longmemeval | raw_fetch | 0.833 | 15386 |
| gpt-5 | longmemeval | search_first | 0.833 | 60 |
| gpt-5-mini | locomo | adaptive | 0.389 | 4354 |
| gpt-5-mini | locomo | digest | 0.389 | 1208 |
| gpt-5-mini | locomo | digest_cfs | 0.500 | 1207 |
| gpt-5-mini | locomo | digest_csf | 0.389 | 1206 |
| gpt-5-mini | locomo | digest_fcs | 0.389 | 1205 |
| gpt-5-mini | locomo | raw_fetch | 0.389 | 10402 |
| gpt-5-mini | locomo | search_first | 0.444 | 107 |
| gpt-5-mini | longmemeval | adaptive | 0.667 | 11724 |
| gpt-5-mini | longmemeval | digest | 0.833 | 1220 |
| gpt-5-mini | longmemeval | digest_cfs | 0.833 | 1207 |
| gpt-5-mini | longmemeval | digest_csf | 0.833 | 1207 |
| gpt-5-mini | longmemeval | digest_fcs | 0.750 | 1217 |
| gpt-5-mini | longmemeval | raw_fetch | 0.750 | 15435 |
| gpt-5-mini | longmemeval | search_first | 0.750 | 60 |
| qwen | locomo | adaptive | 0.389 | 4423 |
| qwen | locomo | digest | 0.389 | 1275 |
| qwen | locomo | digest_cfs | 0.444 | 1278 |
| qwen | locomo | digest_csf | 0.389 | 1288 |
| qwen | locomo | digest_fcs | 0.389 | 1266 |
| qwen | locomo | raw_fetch | 0.278 | 10490 |
| qwen | locomo | search_first | 0.500 | 118 |
| qwen | longmemeval | adaptive | 0.833 | 11711 |
| qwen | longmemeval | digest | 0.750 | 1216 |
| qwen | longmemeval | digest_cfs | 0.750 | 1217 |
| qwen | longmemeval | digest_csf | 0.750 | 1216 |
| qwen | longmemeval | digest_fcs | 0.750 | 1217 |
| qwen | longmemeval | raw_fetch | 0.750 | 15424 |
| qwen | longmemeval | search_first | 0.833 | 60 |

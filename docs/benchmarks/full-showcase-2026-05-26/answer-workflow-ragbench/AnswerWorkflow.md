# Answer Workflow Benchmark

Measures answer correctness, estimated tokens, LLM round trips, search calls, and fetch calls by retrieval strategy.

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

**Answer model**: `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1`  
**Judge model**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1`  

| Strategy | Runs | Accuracy | Mean Tokens | Round Trips | Search Calls | Fetch Calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| summary_only | 36 | 0.7222 | 488.1667 | 1.0 | 0.0 | 0.0 |
| summary_then_search | 36 | 0.75 | 558.8889 | 1.9722 | 0.9722 | 0.0 |
| search_first | 36 | 0.3333 | 132.4444 | 1.0 | 1.0 | 0.0 |
| adaptive | 36 | 0.75 | 1235.1667 | 1.0 | 1.0 | 0.5556 |
| raw_fetch | 36 | 0.7778 | 1591.1944 | 1.0 | 0.0 | 1.0 |
| iterative | 36 | 0.5556 | 443.4167 | 2.2222 | 1.5278 | 0.0 |
| digest | 36 | 0.8333 | 1547.8889 | 1.0 | 1.0 | 0.0 |

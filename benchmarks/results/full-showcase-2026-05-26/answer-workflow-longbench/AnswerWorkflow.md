# Answer Workflow Benchmark

Measures answer correctness, estimated tokens, LLM round trips, search calls, and fetch calls by retrieval strategy.

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

**Answer model**: `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1`  
**Judge model**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1`  

| Strategy | Runs | Accuracy | Mean Tokens | Round Trips | Search Calls | Fetch Calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| summary_only | 32 | 0.4062 | 434.0938 | 1.0 | 0.0 | 0.0 |
| summary_then_search | 32 | 0.4375 | 559.5938 | 1.9062 | 0.9062 | 0.0 |
| search_first | 32 | 0.5312 | 151.0312 | 1.0 | 1.0 | 0.0 |
| adaptive | 32 | 0.5 | 4414.9688 | 1.0 | 1.0 | 0.25 |
| raw_fetch | 32 | 0.5625 | 12843.3125 | 1.0 | 0.0 | 1.0 |
| iterative | 32 | 0.3125 | 755.625 | 4.6562 | 4.5625 | 0.0 |
| digest | 32 | 0.5312 | 1626.3438 | 1.0 | 1.0 | 0.0 |

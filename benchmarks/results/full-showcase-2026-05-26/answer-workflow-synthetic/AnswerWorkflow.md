# Answer Workflow Benchmark

Measures answer correctness, estimated tokens, LLM round trips, search calls, and fetch calls by retrieval strategy.

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

**Answer model**: `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1`  
**Judge model**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1`  

| Strategy | Runs | Accuracy | Mean Tokens | Round Trips | Search Calls | Fetch Calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| summary_only | 35 | 0.7143 | 327.0857 | 1.0 | 0.0 | 0.0 |
| summary_then_search | 35 | 0.7714 | 382.9429 | 1.3714 | 0.3714 | 0.0 |
| search_first | 35 | 0.8286 | 154.2857 | 1.0 | 1.0 | 0.0 |
| adaptive | 35 | 0.7714 | 684.0286 | 1.0 | 1.0 | 0.0286 |
| raw_fetch | 35 | 0.7714 | 8973.6857 | 1.0 | 0.0 | 1.0 |
| iterative | 35 | 0.6571 | 803.0286 | 1.2286 | 0.2 | 0.0571 |
| digest | 35 | 0.7429 | 2000.4286 | 1.0 | 1.0 | 0.0 |

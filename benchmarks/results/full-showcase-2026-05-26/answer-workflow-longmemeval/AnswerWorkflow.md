# Answer Workflow Benchmark

Measures answer correctness, estimated tokens, LLM round trips, search calls, and fetch calls by retrieval strategy.

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

**Answer model**: `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1`  
**Judge model**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1`  

| Strategy | Runs | Accuracy | Mean Tokens | Round Trips | Search Calls | Fetch Calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| summary_only | 12 | 0.75 | 378.25 | 1.0 | 0.0 | 0.0 |
| summary_then_search | 12 | 0.75 | 412.5833 | 2.0 | 1.0 | 0.0 |
| search_first | 12 | 0.6667 | 59.5833 | 1.0 | 1.0 | 0.0 |
| adaptive | 12 | 0.75 | 11693.6667 | 1.0 | 1.0 | 0.75 |
| raw_fetch | 12 | 0.5 | 15404.8333 | 1.0 | 0.0 | 1.0 |
| iterative | 12 | 0.6667 | 4255.4167 | 4.3333 | 3.75 | 0.25 |
| digest | 12 | 0.75 | 1460.5 | 1.0 | 1.0 | 0.0 |

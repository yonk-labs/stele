# Answer Workflow Benchmark

Measures answer correctness, estimated tokens, LLM round trips, search calls, and fetch calls by retrieval strategy.

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

**Answer model**: `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1`  
**Judge model**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1`  

| Strategy | Runs | Accuracy | Mean Tokens | Round Trips | Search Calls | Fetch Calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| summary_only | 18 | 0.2778 | 450.6667 | 1.0 | 0.0 | 0.0 |
| summary_then_search | 18 | 0.2778 | 541.3333 | 2.0 | 1.0 | 0.0 |
| search_first | 18 | 0.2778 | 120.5 | 1.0 | 1.0 | 0.0 |
| adaptive | 18 | 0.4444 | 4421.8889 | 1.0 | 1.0 | 0.3889 |
| raw_fetch | 18 | 0.5556 | 10488.0556 | 1.0 | 0.0 | 1.0 |
| iterative | 18 | 0.2778 | 520.2222 | 3.5 | 3.1111 | 0.0 |
| digest | 18 | 0.5 | 1287.5 | 1.0 | 1.0 | 0.0 |

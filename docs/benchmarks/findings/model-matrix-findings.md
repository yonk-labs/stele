# Model matrix — findings & honest caveats (2026-05-27)

Interpretation of `model-matrix-2026-05-27.md` (the auto-generated tables).
Matrix: Mem0 vs stele across 6 answerers (qwen, gemma, gpt-4/gpt-4-turbo,
gpt-4o, gpt-5-mini, gpt-5) × {LoCoMo, LongMemEval}, **judge held constant at
gpt-4o**. Raw artifacts in this directory.

## The headline caveat: N is too small to rank strategies

LoCoMo n=18, LongMemEval n=12. Re-running the *same* config gave swings of
**±0.10–0.17** (e.g. raw_fetch LoCoMo 0.667 then 0.556; search_first
0.611/0.667/0.778). Almost every strategy/model difference below is *inside*
that band. **At this N the benchmark cannot reliably rank packings or models.**
Treat single-cell numbers as noise; trust only effects that are large and
repeated.

### Correction to an earlier claim
An earlier write-up (now corrected) argued "summarization is a crutch — it helps
weak models and hurts strong ones." The matrix does **not** support that. digest
− raw-chunks on LoCoMo: qwen **−0.11** (hurt the weak model), gpt-4o **+0.17**
(helped the strong model) — the opposite of the claim, and all within noise. The
original was an artifact of one run where qwen's raw-chunk score happened to be
0.278 (it's 0.500 here). Lesson logged: do not narrate single-run deltas at n=18.

## What is robust (survives the noise / is structural)

1. **gpt-4 (8k context) cannot hold full context.** raw_fetch (~10k tokens)
   hard-errors with `context_length_exceeded` (9772 > 8192). A concrete,
   non-statistical argument for retrieval/digest over full-context dumping.
   (The matrix's "gpt-4" answerer row is therefore gpt-4-turbo/128k.)

2. **LongMemEval saturates at this N.** Every strategy × model lands 0.75–0.83.
   The benchmark/N isn't discriminating here; don't read rankings from it.

3. **Block order (summary/facts/chunks) doesn't matter.** All of SFC/FCS/CSF/CFS
   land within noise of each other across qwen/gpt-4o/gpt-5-mini. No order wins.

4. **Mem0 is remarkably consistent across answerers; stele's lanes are not.**
   Mem0 LoCoMo: **0.56–0.72 regardless of answerer** (qwen 0.72, gemma 0.56,
   gpt-4 0.67, gpt-4o 0.67, gpt-5-mini 0.67, gpt-5 0.61). stele's retrieval lanes
   swing 0.28–0.83 with answerer/strategy. Mem0's LLM-distilled, compact
   (~540-token) memories give answerer-robust results — a real qualitative
   difference, even if absolute accuracy is similar to stele's better configs.

5. **The Mem0 cost is at ingest, not read.** Mem0 spends **~190–300 s of LLM
   extraction per conversation set** at write-time (plus per-write LLM cost),
   then retrieves ~540 compact tokens. stele's indexing is deterministic
   (no LLM at write) and reads more tokens (digest ~1.2k, full ~10–15k). So the
   real Mem0-vs-stele tradeoff is **write-time LLM cost + compact reads (Mem0)**
   vs **zero-LLM deterministic writes + larger reads (stele)** — not accuracy,
   which is a wash at this N.

## What this does NOT tell us (needs higher N)
- Whether summarization helps/hurts per model (the digest deltas are noise).
- Whether any stele strategy beats Mem0 on accuracy (wash at n=18).
- Whether gpt-5 prefers full context (its LoCoMo raw_fetch 0.667 > digest 0.389
  is suggestive but single-run).

## Recommended next step
Re-run the **headline only** — LoCoMo, answerers {qwen, gpt-4o, gpt-5}, lanes
{search_first, digest, raw_fetch} + Mem0 — at **n ≥ 100** (full LoCoMo QA set),
judge gpt-4o, 1 pass. That's the minimum to make any accuracy ranking
defensible. Everything else here is either structural (robust) or noise (not).

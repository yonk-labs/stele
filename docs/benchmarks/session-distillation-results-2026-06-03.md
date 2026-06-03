# Session Distillation: Real Agent Transcripts (2026-06-03)

Distilling the six memory modes from **real agent transcripts**, the honest target
that the curated-CLAUDE.md path was a poor proxy for. Pipeline:
`Stele.extract.from_session` (parse transcript -> window failures-first ->
LLM-extract kinded memories with evidence) feeding the `Stele.distill` views.
Harness: `benchmarks/external/memory_modes/session_distill.py`. LLM: Qwen (local).

## Run: 40 real sessions, one per project (diverse-first), 3 windows each

- **279 durable memories** committed (30 sessions yielded content; 10 were thin /
  tool-only and yielded 0, honest).
- By kind: ~104 fact, 33 pitfall, 26 workaround, 24 instruction, 12 preference, 8 decision.

### Distilled views (over all 40)

**Rules (11, normalized to don't / do_instead):**
- cd to wrong working directory -> verify cwd and correct path before cd
- use em-dash (U+2014) directly in command text -> use ASCII hyphen or escape it
- edit/write a file without reading it first -> read it first
- edit a file modified since it was read -> re-read before editing
- read a file that does not exist -> check existence first

**Skills (5):** always read before editing; retry transient failures with
exponential backoff; never trust a single judge (direction varies by dataset).

**Best practices (12):** prefer uv over venv/pip; never conflate chunkshop_api
with chunkshop; treat benchmark runs as gitignored regenerable artifacts; keep
workgraph deterministic and free of LLM/network imports; single-page architecture
over fragmented docs.

**Precedents (10, including rework):** abandoned inline process orchestration for
a self-contained e2e script; chose Option B workaround to fix CI immediately;
chose 'living-kb' for clarity/availability/no-trademark; bumped to 0.5.0a1 not
0.4.1 due to substantial new code; set harness max_iterations to 25 to match
LangGraph's default.

**Facts (104):** real project facts mixed with ephemeral test-fixture state.

## What works
- Real transcripts in, useful distilled memory out, at scale, across diverse projects.
- The richest signal is captured: **rules are mined from real failures** (worktree
  conflicts, token-limit reads, read-before-edit errors) and paired with the fix.
- First-class core API (`Stele.extract.from_session`), format-pluggable for
  non-Claude agent loops, resumable/paginated harness (`--start`/`--no-purge`).
- Full suite green: 995 passed / 16 skipped; ruff + canonical mypy clean.

## Honest residuals (next quality work)
1. **Semantic dedup.** The read-before-edit rule surfaces ~5 ways (per file:
   "edit MEMORY.md without reading", "edit pyproject.toml without reading", ...).
   Normalized-exact dedup does not collapse them. Needs embedding-based dedup or
   LLM canonicalization. Recurrence evidence (merged refs) is already tracked.
2. **Fact precision.** `distill_facts` has no LLM refine, so it surfaces ephemeral
   test-fixture state ("hello.txt contains hello", "/tmp/pytest-.../"). Facts need
   a precision pass or the extractor should skip ephemeral/session-local state.
3. **View volume at full scale.** 33 rules / 104 facts from 40 sessions; the full
   7242-session corpus would be thousands. Views need ranking/capping (top-N by
   recurrence + confidence).
4. **Throughput.** Extraction is sequential LLM calls (~30s/session). The refine
   is bucketed (context-safe at any scale); ingest needs concurrency for the full
   corpus, and is already resumable in buckets via `--start`.

## Reproduce
```bash
STELE_PG_DSN=postgresql://.../stele_bench \
  .venv/bin/python -m benchmarks.external.memory_modes.session_distill \
    --limit 40 --per-session-windows 3 --distill
# resume in buckets: --start 40 --no-purge --limit 40
```

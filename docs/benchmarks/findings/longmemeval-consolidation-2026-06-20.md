# LongMemEval cannot measure stele's evolving-fact consolidation (2026-06-20)

**Question:** does evolving-fact consolidation (the `from_session` subject/aspect
supersession feature shipped in 0.6.3) improve answer accuracy on LongMemEval
knowledge-update questions?

**Verdict: the benchmark cannot exercise the feature.** Not a tuning gap — an
extraction-target mismatch. Consolidation is real and proven elsewhere (contract
tests + a real-LLM cross-session case); LongMemEval just can't see it.

## Method

`benchmarks/longmemeval_consolidation.py`: for each LongMemEval `knowledge-update`
record, ingest every haystack session through `Stele.extract.from_session` (the
consolidation path), then answer the question from `memory.search` and judge vs
gold. Run with `extraction.consolidation_enabled` ON vs OFF (the new toggle).
Answerer = qwen (`Intel/Qwen3-Coder-Next-int4-AutoRound`); judge = gemma
(`cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit`). Flags: `--max-windows`, `--recall-limit`,
plus per-record diagnostics (memories stored, chains formed, recalled set vs gold).

## Result

10-record probe, `--max-windows 8 --arm both`:

| Arm | Accuracy | Mean accepted | Supersessions / chains |
|-----|---------:|--------------:|------------------------|
| ON  | 0.70 | 4.0 | 0 / 0 |
| OFF | 0.70 | 5.1 | 0 |

Tied. **Zero supersessions across all records** (raising `max_windows` 3→8 did not
change this).

## Root cause

LongMemEval's evolving facts are **personal-life facts** (a 5K race time, a count
of Korean restaurants, a move to the suburbs) embedded in **coding conversations**.
stele's extractor targets technical / rule / decision facts, so the answer-bearing
personal facts are **never extracted** → no `(subject, aspect)` slots form → there
is nothing for consolidation to supersede. Diagnostics on the wrong-answer records
confirmed verdict (i): the answer-bearing fact was never in the store (recalled
memories were about unrelated code). More extraction windows surface more *code*
facts, not the personal facts the questions need. This is a hard ceiling.

## No regression

The probe's apparent yield gap (ON 4.0 vs OFF 5.1 mean accepted) was **extraction-LLM
sampling noise** — ON and OFF ran as separate LLM samples. A deterministic
fake-LLM check (same fixed extraction, ON vs OFF) accepted the **identical** memory
set. Consolidation does not drop memories.

## Conclusion

- LongMemEval is the **wrong yardstick** for stele's consolidation: its evolving
  facts live outside stele's extraction target.
- Consolidation remains **mechanism-proven** (`tests/contract/test_consolidation_from_session.py`)
  and **real-LLM-proven** (a cross-session "Task 3: blocked → done" case
  consolidated correctly end-to-end).
- A fair outcome benchmark would need evolving-fact pairs *inside agent/coding
  sessions*, or a personal-fact-aware extraction mode that targets user
  measurements/preferences/schedules separately from technical content.

## Artifacts (in this branch)

- `src/stele/core/config.py`: `ExtractionConfig.consolidation_enabled` toggle
  (default True; the escape hatch + A/B lever).
- `benchmarks/longmemeval_consolidation.py`: the ON/OFF adapter (kept as a
  documented benchmark; re-runnable with `--limit`, `--max-windows`, `--arm`).

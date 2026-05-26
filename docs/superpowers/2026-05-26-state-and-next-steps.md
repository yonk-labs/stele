# State & Next Steps — digest_search + grounding benchmark (waiting on upstream)

Date: 2026-05-26
Branch: `feat/full-benchmark-showcase`
Status: **Blocked on upstream releases.** Design phase complete; specs at the
user-review gate; no implementation started (hard gate — no code until specs
approved AND deps land).

Supersedes the stale parts of `2026-05-23-digest-search-handover.md`. This is
the single source of truth for current state.

## One-paragraph summary

We designed a new recall strategy, **`digest_search`** — query-driven fast-mode
recall that searches, expands query terms, soft-ranks, summarizes the retrieved
chunks into one compact query-biased summary (lede `readable_report`), sends the
summary as `context`, and keeps full chunks cited for escalation. A **sibling
grounding-benchmark spec runs first** to set its defaults via honest baselines on
larger docs with a graded answer-equivalence judge. Separately, we audited
**pg-raggraph** and decided not to migrate to its new retrieval-profile ladder
yet (API not in the pinned version). Everything is committed locally; nothing is
pushed.

## Committed (local, unpushed — 8 commits on top of `8704b5f`)

| Commit | What |
|---|---|
| `dee68fc` | digest_search v1 spec |
| `8b0d2cd` | (older) session handover — partly superseded by this file |
| `199647b` | digest_search → lede 0.4.4 `readable_report` (winner composition + dedup fix) |
| `2a92fa0` | benchmark extracted to a sibling spec |
| `8e361fe` | recall grounding benchmark spec (runs first) |
| `3160139` | notes on lede 0.4.5 features |
| `dadf9da` | applied lede 0.4.5 action items to both specs |
| `4b15124` | pg-raggraph retrieval-profile migration audit |

Key documents:
- Spec A (depends on B): `docs/superpowers/specs/2026-05-22-digest-search-recall-design.md`
- Spec B (runs first): `docs/superpowers/specs/2026-05-23-recall-grounding-benchmark-design.md`
- lede notes: `docs/superpowers/2026-05-23-lede-0.4.5-features.md`
- pg-raggraph audit: `docs/superpowers/2026-05-24-pg-raggraph-profile-audit.md`

Untracked, NOT ours (leave alone): `.stele/`, `benchmarks/external/preserved/`.

## Locked design decisions

- **`digest_search`** = a new dedicated recall strategy (not an `adaptive`
  extension), built on stele's EXISTING retrieval. chunkshop 0.5.0 native-search
  migration is a deferred **slice 2**.
- **Summarizer** = `lede.readable_report` (the bake-off winner: hint-biased
  summary + hint-biased `key_facts`). chunkshop `summarize_hits` **dropped**
  (lede underneath). Slice 1 uses only the compact `.to_markdown()` human
  surface.
- **Invariant**: `recall/` must not import lede/chunkshop
  (`tests/unit/recall/test_architecture.py`). Summarizer + expander live under
  `summary/`, injected via `_RecallDeps`, constructed in `core/stash.py`.
- **Config**: size-gate (skip summarization below N tokens) + adaptive budget
  (floor/ceiling scaling with returned size) replace any fixed char cap;
  `report_backend="regex"` default (spaCy opt-in — it adds `correlate_facts`,
  the worst bake-off lane); expansion opt-in (`expansion_kinds=()`).
- **Grounding benchmark first**: it sets digest defaults + ship/no-ship.
  Lanes = {cold_llm, full_doc, chunks_10/20/30, digest_regex, digest_spacy,
  scenarios d–f}. Corpora = SCOTUS (+~40 authored gold, incl. a deterministic-
  attribute subset) + LongBench-long + MHR (medical-hrt). Judge = graded
  0/0.5/1 answer-equivalence via `rejudge.py` replay. Prereq: raise the
  ~2000-char ingest truncation cap. n≈60/dataset.
- **pg-raggraph**: no change now; staged migration documented (swap
  `mode/rerank → profile` in the revisor on release + pin bump).

## Blocked on upstream (what we are waiting for)

1. **pg-raggraph profile-API release** — pinned `0.3.0a3` has no `profile=` on
   `GraphRAG.query`. Staged migration in the audit doc fires when a release lands
   and the `postgres-graph` pin is bumped. Also brings the graph-hydration
   latency fix (`idx_entity_chunks_chunk`, relationship-ID-first CTEs) and
   namespace-profile migrations. Under active upstream dev — do not pre-empt.
2. **Local dependency installs / availability** — `.venv` still has lede 0.3.0
   and chunkshop ~0.4.x; PyPI was unreachable from the sandbox. Before ANY code:
   `pip install 'lede>=0.4.5,<0.5' lede-spacy>=0.4.5` (+ spaCy model for
   expansion) and run the before-commit trio to confirm the lede core-dep bump
   is byte-safe.
3. **chunkshop PR #40** — if/when slice 2 uses chunkshop 0.5.0, verify the PR #40
   fix is present before relying on its benchmark path.

## Open items requiring the user (review gate)

- **Grounding-benchmark spec review** — still awaiting sign-off before
  `writing-plans`. Specific spots flagged: SCOTUS gold size (~40) and who authors
  it (manual, on the critical path); `n≈60/dataset`; the d–f scenario set.
- After approval, the brainstorming flow transitions to **`writing-plans`**, and
  the grounding benchmark is planned FIRST (it gates digest defaults).

## Next steps (ordered, resume here)

1. **(User)** Approve / adjust the grounding-benchmark spec.
2. When deps are installable: `pip install lede>=0.4.5 lede-spacy`; run
   `.venv/bin/ruff check .` · `.venv/bin/mypy src tests benchmarks` ·
   `.venv/bin/pytest` to prove the lede bump is byte-safe.
3. Invoke `writing-plans` for the grounding benchmark spec; execute it; record
   the winning digest defaults + ship/no-ship.
4. Plan + implement `digest_search` using those defaults.
5. When pg-raggraph releases the profile API + pin bump: execute the staged
   migration in `2026-05-24-pg-raggraph-profile-audit.md` (one config field, two
   revisor call sites, one optional recall param, one integration test).

## What to remember (durable)

- postgres is the default backend for tests/benchmarks; ASK before adding
  sqlite/memory/other backends.
- Don't write to branches another agent is working; pg-raggraph is under active
  upstream dev — wait for the release.
- Accuracy claims require the answer-workflow benchmark, not the showcase.
- The bake-off winner is `summary + hint-biased key_facts` (50% acc / 67% tok
  reduction); per-chunk summarization and structured S-R-V (`correlate_facts`)
  both lose; over-focusing hints (0.95) hurts.
- lede has two output surfaces: compact human (markdown/text) for LLM context,
  full JSON (attributes/fact_records/promotion_candidates/search_text) for
  ingest/FTS/metadata-promotion — the JSON path is slice-2 territory.

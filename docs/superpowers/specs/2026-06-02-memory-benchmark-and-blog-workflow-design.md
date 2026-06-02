# Memory Benchmark + Benchmark-to-Blog Workflow Design

Date: 2026-06-02
Status: Design (implementation-ready)
Scope: a pluggable multi-mode memory benchmark that tests stele where memory *diverges* from RAG, plus the reusable workflow that turns benchmark runs into blog posts.

---

## 1. Purpose and the honest framing

The first attempts this session (`benchmarks/external/memory_recall_lane.py`, `benchmarks/external/memory_vs_rag_matrix.py`) measured memory the way you measure RAG: hand the answerer a document (or a flattened conversation), retrieve, grade with an LLM judge. In that regime memory *loses*. And it should. The published result was blunt: in single-document QA where the whole document is also available, a memory store scored ~0.10 against document RAG's ~0.65 (LoCoMo, n=40). That number is real and we are not going to hide from it. It is also the wrong question.

**Memory is not RAG.** RAG retrieves passages that look like the query, from a corpus that is present. Memory answers questions about a history that has already scrolled out of the context window, where there is no document to retrieve from because the only record is what was written to the store. The interesting regime, the one this benchmark exists to measure, is exactly where those two diverge:

- The conversation is long enough that the relevant turn is no longer in the prompt.
- The answer depends on *which assertion won* (supersession), not on which passage is most similar.
- The answer is a *rule to obey across turns*, not a fact to look up once.
- The relevant unit is a *prior task episode*, recalled and re-used, that never existed as a passage in any document.

**Deterministic over flaky judges.** The same session measured the LLM judge flapping 0.80 on one run and 0.22 on a rejudge of the same answers. An LLM-as-judge in the scoring loop is a coin we cannot afford to flip when a headline number rides on it. So every mode here has a deterministic primary metric: a `recall@K` set-intersection, an exact-match against an atomic gold, a closed-vocabulary state classification, or a regex violation count. The judge survives only as an optional, clearly-labeled diagnostic column, never the headline.

This document specifies six benchmark modes (four detailed in full, plus two enforcement-twins that reuse the same harness), a pluggable harness that runs them as N-extensible plugins, and a reusable benchmark-to-blog workflow with honesty gates baked in. The six split three ways by access pattern: similarity-recall, structured-state-lookup, and enforcement (which itself splits into negative guardrail, positive skill, and suggested best practice). Everything is grounded in the real stele code read for this design (`src/stele/core/memory.py`, `src/stele/core/memory_record.py`, `src/stele/workgraph/`, and the existing `benchmarks/external/` lanes).

### What this is built on (verified against the code)

- **Memory facade** (`src/stele/core/memory.py`):
  - `memory.add(*, text, kind, source_refs, scope, summary, detail, action, supersedes, confidence, metadata) -> MemoryAddResult` (line 67). `source_refs` must be non-empty `stele://` URIs or `MemoryRecord._validate_source_refs` raises `ValidationError` (memory_record.py:93-105).
  - `memory.add_many(items: list[AddRequest]) -> list[MemoryAddResult]` (line 159).
  - Re-observation is automatic: a duplicate text in-scope with no `supersedes` calls the store's internal `confirm`, bumping `confirmations` and evolving `confidence` via `evolved_confidence` (memory.py:114-123). **There is no public `Memory.confirm` method**. The public confirmation path is re-calling `add` with identical text+scope; the `MemoryAddResult.duplicate_of` field is set when this happens.
  - `memory.search(MemoryQuery)` (line 268), `memory.search_with_score(query, scope, *, limit=5, source_ref_filter=None) -> list[ScoredMemoryHit]` (line 349), `memory.list(scope, status_filter=None, limit=100, *, as_of=None)` (line 271). `memory.update(...)` rejects text edits and redirects to `add(supersedes=[id])` (line 284-294).
  - The keyword-vs-vector recall switch is `RetrievalConfig.memory_vector` (config.py:69, default `False`). `True` fuses tsvector + pgvector via RRF on Postgres.
- **`MemoryRecord`** (memory_record.py): tripartite `summary`/`detail`/`action` (all optional), plus `confidence`, `confirmations`, `last_confirmed`, `last_queried`, `status`, `supersedes`, `effective_from`/`effective_until`, `metadata`. `indexable_text` joins the tripartite fields when present, so FTS ranks on the structured view (line 85-91). `MemoryKind` is the closed Literal `{fact, preference, decision, instruction, commitment, issue, summary, pitfall, workaround, tool_recommendation, tool_gap}` (line 14-29).
- **`MemoryScope`** (memory_record.py:44): frozen model with `user_id`, `agent_id`, `app_id`, `session_id`, `namespace`.
- **WorkGraph** (`src/stele/workgraph/`): **not** on the `Stele` facade. `Stele` exposes only the `memory`/`extract`/`recall` properties (stash.py:953-1024); there is no `Stele.workgraph`. A benchmark must construct a store directly: `SQLiteWorkGraphStore(db_path)` (supports `as_of`) or `InProcessWorkGraphStore` (raises `CapabilityError` on `as_of`). `TaskNode.status` is the Literal `{pending, active, done, blocked, failed, superseded}` (models.py:23). `WorkGraphStatus` (graph level) is `{active, paused, completed, failed, abandoned}` (models.py:18). `validate_status_transition` (validators.py:46-56) enforces legal node moves and permits `pending|active|blocked -> abandoned`. Note the code inconsistency: the validator allows `abandoned` as a node target but `NodeStatus` does not list it; the benchmark must therefore route an "abandoned feature" to node `status="failed"` (a valid `NodeStatus`) and/or graph `status="abandoned"`. See Mode `resume-task-state`.
- **Harness helpers to reuse, never reinvent:**
  - `benchmarks/external/cross_corpus_matrix.py::_units(corpus, budget) -> list[(unit_id, content, [(question, gold)])]` (line 45). LoCoMo loader, drops category-5 temporal-unanswerable, caps Q/conversation.
  - `benchmarks/external/sweep_matrix.py`: `_QWEN`, `_GEMMA`, `_answer`, `_rr`, `_store`, `_pack` (lines 38, 39, 44, 83, 98). `_rr` is reciprocal rank: substring for short gold, content-word overlap for long gold.
  - `benchmarks/external/cascade_shootout.py::_answer(ans, ctx, q)` (line 73). The "answer using ONLY this context" prompt.
  - `benchmarks/answer_workflow.py::OpenAICompatAnswerer`. Answer = Qwen @ `http://192.168.1.193:8000/v1`, judge = Gemma @ `http://192.168.1.133:8000/v1`. It re-exports `estimate_tokens` from `stele.core.artifact` (answer_workflow.py:33), so token accounting can import from either `stele.core.artifact` or `benchmarks.answer_workflow`.
  - `benchmarks/external/rejudge_aw.py::_jscore_correct(judge, *, question, expected, answer)` (line 80). Mem0-style J-score, lenient, generated-vs-gold only. Loaded via `importlib.util.spec_from_file_location` the same way `sweep_matrix` does.
- **Output conventions:** JSON results go to `benchmarks/runs/cq-additive/<name>-<UTCstamp>.json` (stamp = `time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())`). The directory exists (e.g. `memory-recall-20260602T112634Z.json`, `memory-vs-rag-20260602T114046Z.json`). **Never touch `MEGA-GRID`.** Blogs go to `~/blogs/MM-DD-YYYY-slug.md`; persona `the-yonk` lives at `~/.claude/personas/the-yonk.md`; prior posts (`06-02-2026-your-agent-cant-find-what-it-remembers.md`) are the honesty-and-voice reference.

---

## 2. The memory taxonomy and the three access patterns

A memory store is not used one way. The mistake in the first attempts was treating "recall" as the only verb. There are three distinct access patterns, and they stress different parts of stele. Modes are organized around access pattern, not around corpus.

| Access pattern | The agent question | Stele mechanism | Why RAG can't do it |
|---|---|---|---|
| **similarity-recall** | "Have I seen this before? When did I X? Do I already know this?" | `memory.search_with_score(q, scope)` over `fact`/`decision` memories, ranked on `indexable_text` | RAG *can* do this when the document is present; the divergence is when history has scrolled out and the store is the only record. |
| **structured-state-lookup** | "Where did we leave off on X? Is feature Y done? Did we ever build Z?" | supersession head (`add(supersedes=[...])` + `list(status_filter=None)` newest-valid view) and WorkGraph `TaskNode.status` (`query_graph`), entity-keyed, NOT similarity | There is no "relevant passage." The answer is *which assertion won* and *which subtask is marked done*. A similarity retriever returns the nearest feature and invents a status. |
| **enforcement** | "Obey this rule on every turn." | rule stored as `instruction`/`pitfall`/`workaround`; injected via selective recall; corrected by `add(supersedes=[...])` | A retriever surfaces a rule; it cannot *enforce* one, and it has nowhere durable to persist a correction across sessions. |

The **six** modes map onto these patterns:

- `fact-recall` -> **similarity-recall** (sentence-grained facts)
- `precedent-recall` -> **similarity-recall** (episode-grained task records)
- `resume-task-state` -> **structured-state-lookup**
- `guardrail-adherence` -> **enforcement** (negative: "never do this")
- `skill-adherence` -> **enforcement** (positive: "always do this")
- `best-practice` -> **enforcement** (suggested: "consider doing this")

Two modes share the similarity-recall pattern but at different grain (a sentence vs. a whole prior task episode), which is why they are separate modes rather than one. Three modes share the enforcement pattern but differ in polarity and force: a negative prohibition, a positive habit, and a soft suggestion. They share the §4.4 harness (a `RuleChecker` family) and differ only in detector polarity and default behavior.

### 2.1 The suggest-not-force principle (governs the enforcement trio)

Behavioral memory **suggests, it does not force.** A learned rule (`guardrail`, `skill`, or `best-practice`) is, by default, *surfaced* when relevant and the agent decides; it is *auto-applied* only when the operator opts in. So each enforcement mode is scored in **two settings**, and the difference between them is itself a result:

- **suggest mode (default):** did recall surface the right rule at the right moment? Metric is the precision/recall of *which rules got surfaced* for a task (deterministic set math), independent of whether the agent then obeyed.
- **auto-accept mode (opt-in):** with the rule injected/enforced, did the output actually comply? Metric is the violation rate (guardrail), application rate (skill), or take-up rate (best-practice).

`best-practice` is suggest-only by construction: it never has an auto-accept setting, because a best practice that auto-enforces is just a guardrail. That asymmetry is the point of keeping it a separate mode.

---

## 3. The pluggable harness architecture (modes are N-extensible)

The harness runs the six modes as plugins over one shared runner. A Mode owns *how memory gets populated*, *how one case is exercised under each condition*, and *how the result is scored*. The runner knows nothing about what a mode measures; it iterates `modes x conditions x cases`, owns the answerer/judge wiring and the namespace lifecycle, and writes one consolidated JSON. Adding a mode is one file plus one line in a registry. No runner edit, no schema migration.

New package: `benchmarks/external/memory_modes/` (a package, because six modes plus a runner exceed one file). No console entry point; run as `python -m benchmarks.external.memory_modes.run`.

### 3.1 The Mode interface

```python
# benchmarks/external/memory_modes/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from stele.core.stash import Stele

Condition = str  # "no_memory" | "prompt_stuffed" | "memory_driven"

@dataclass(frozen=True)
class Case:
    """One scored unit of work. `payload` is mode-private."""
    case_id: str
    question: str            # the probe ("when did I paint the sunrise?")
    gold: str                # deterministic expected answer where possible
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass
class CaseResult:
    """What run_case produced under one condition, before scoring."""
    output: str              # the model answer OR the produced artifact text
    metric: dict[str, float] # mode-defined: {"recall_at_k": 1.0, ...}
    tokens_in: int           # context/prompt tokens charged to memory's account
    tokens_out: int
    deterministic: bool      # True if `metric` needs no LLM judge
    extra: dict[str, Any] = field(default_factory=dict)  # mrr, retr_ms, refs

@runtime_checkable
class Mode(Protocol):
    name: str                       # stamped into results, e.g. "fact_recall"
    conditions: tuple[Condition, ...]  # a mode may legitimately skip one
    deterministic: bool             # True if the mode never calls an LLM judge
    # The honesty box, copied verbatim into the consolidated doc / blog:
    measured: str
    not_measured: str

    def populate(self, store: Stele, corpus: list[Case]) -> None:
        """Seed durable state ONCE: store artifacts, memory.add(...),
        WorkGraph nodes. Idempotent against a purged namespace."""

    def run_case(self, store: Stele, case: Case, condition: Condition) -> CaseResult:
        """Exercise ONE case under ONE condition: retrieval/lookup/enforcement
        + the LLM call (via the shared _answer). No scoring here."""

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        """Deterministic where possible. resume_task_state and
        guardrail_adherence are pure-Python; fact/precedent may add a judge
        diagnostic but always carry a judge-free number too."""
```

That is the whole contract: three methods (`populate`, `run_case`, `score`) plus five declarative attributes. A mode declaring a two-condition subset (e.g. `resume_task_state` has no honest `prompt_stuffed` baseline once history exceeds the window) is handled by the runner without special-casing.

### 3.2 The shared runner

```python
# benchmarks/external/memory_modes/run.py  (sketch)
def run(modes, conditions_filter, corpora, per_corpus, out_dir, dsn, seed):
    ans, judge = _answerers()        # exact reuse of OpenAICompatAnswerer config
    rows, agg = [], {}
    for mode in modes:
        for corpus in corpora:
            cases = load_corpus(mode, corpus, per_corpus, seed)
            store = _store_for(mode, dsn)        # fresh Stele per mode
            ns = f"memmode-{mode.name}-{corpus}"
            try: store.purge_namespace(ns)       # idempotent reset
            except Exception: pass
            mode.populate(store, cases)
            for case in cases:
                rec = {"mode": mode.name, "corpus": corpus, "case": case.case_id,
                       "question": case.question, "gold": case.gold, "conditions": {}}
                for cond in mode.conditions:
                    if conditions_filter and cond not in conditions_filter:
                        continue
                    res = mode.run_case(store, case, cond)
                    metric = mode.score(case, res)
                    rec["conditions"][cond] = {**metric,
                        "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                        "deterministic": res.deterministic, **res.extra}
                rows.append(rec)
            store.close()
    return rows  # aggregated into agg[mode][corpus][condition] by the writer
```

The runner is the only place that touches the judge/answerer wiring, the namespace lifecycle, and the JSON write. Modes never write files.

### 3.3 Results JSON schema (additive, stamped, MEGA-GRID-safe)

Same top-level `{config, agg, rows}` shape as the existing `cq-additive` files, extended with a `mode` axis. `agg` is keyed `mode -> corpus -> condition`, a superset of the existing `corpus -> lane` shape, so a reader that walks `agg[corpus]` still parses (it sees `mode` on top). Written to `benchmarks/runs/cq-additive/multimode-<stamp>.json`.

```jsonc
{
  "config": "memory-modes harness / access-pattern x condition / deterministic-where-possible",
  "stamp": "20260602T120000Z",
  "endpoints": {"answer": "http://192.168.1.193:8000/v1", "judge": "http://192.168.1.133:8000/v1"},
  "modes": ["fact_recall", "precedent_recall", "resume_task_state", "guardrail_adherence"],
  "agg": {
    "fact_recall": {
      "locomo": {
        "memory_vec":     {"recall_at_k": 0.78, "exact_match": 0.61, "tokens_in": 640, "n": 40},
        "prompt_stuffed": {"recall_at_k": 1.00, "exact_match": 0.74, "tokens_in": 8200, "n": 40},
        "no_memory":      {"recall_at_k": 0.00, "exact_match": 0.05, "tokens_in": 0, "n": 40}
      }
    },
    "guardrail_adherence": {
      "synthetic-rules": {
        "memory_driven":  {"violation_rate_r0": 0.42, "violation_rate_r1": 0.05, "guard_tokens": 18, "n": 20},
        "prompt_stuffed": {"violation_rate_r0": 0.40, "violation_rate_r1": 0.38, "guard_tokens": 480, "n": 20},
        "no_memory":      {"violation_rate_r0": 0.90, "violation_rate_r1": 0.90, "guard_tokens": 0, "n": 20}
      }
    }
  },
  "rows": [
    {"mode": "fact_recall", "corpus": "locomo", "case": "loc-12-q3",
     "question": "When did Melanie paint a sunrise?", "gold": "8 May 2023",
     "conditions": {
       "memory_vec":     {"recall_at_k": 1.0, "exact_match": 1.0, "tokens_in": 612, "tokens_out": 11, "mrr": 1.0, "retr_ms": 8.3, "deterministic": true},
       "prompt_stuffed": {"recall_at_k": 1.0, "exact_match": 1.0, "tokens_in": 8201, "tokens_out": 12, "deterministic": true},
       "no_memory":      {"recall_at_k": 0.0, "exact_match": 0.0, "tokens_in": 0, "tokens_out": 9, "deterministic": true}
     }}
  ]
}
```

Two reporting axes are first-class because both are load-bearing: the per-mode metric AND `tokens_in`, so the token-reduction story is visible directly in `agg` as the fact/rule/episode count grows.

### 3.4 Files this section creates (all new, additive)

- `benchmarks/external/memory_modes/base.py`. `Mode` Protocol, `Case`, `CaseResult`.
- `benchmarks/external/memory_modes/registry.py`. The `MODES` list (the single extension point).
- `benchmarks/external/memory_modes/{fact_recall,precedent_recall,resume_task_state,guardrail_adherence,skill_adherence,best_practice}.py`. One file per mode; the last two reuse the `guardrail_adherence` `RuleChecker` machinery.
- `benchmarks/external/memory_modes/corpora.py`. A `CorpusSource` abstraction with **two** implementations per mode, both first-class (run either or both, labeled in results):
  - **`synthetic`** (seeded, inline, deterministic): for CI, network-free smoke, and reproducibility.
  - **`real_trace`** (mined from actual stele data): the LoCoMo adapter over `_units` for fact-recall, and a trace miner over the project's own real artifacts for the state/behavioral modes: `.remember/` session history and WorkGraph event logs (resume-task-state: actual "what we did / where we left off"), recorded corrections and rules (guardrail/skill/best-practice: e.g. the real "no em-dashes" rule), and the live memory store rows (fact/precedent). Real traces blunt the "authored to pass" critique; synthetic guarantees determinism. Per-mode fit varies (state/behavioral modes mine cleanly; fact/precedent need derived QA pairs), so a mode may ship `real_trace` for some sources and synthetic-only where no honest gold can be derived. Results label every number with its source.
- `benchmarks/external/memory_modes/run.py`. Shared runner + JSON writer; entry `python -m benchmarks.external.memory_modes.run`.
- Output: `benchmarks/runs/cq-additive/multimode-<stamp>.json` (never MEGA-GRID).

### 3.5 A 5th mode plugs in with zero runner changes

Example: split positive *skill* adherence (DO use the project's logging helper) from negative *guardrail* (DON'T use em-dashes). Create `skill_adherence.py` implementing the same Protocol. `populate` stores `kind="instruction"` skill rules, `run_case` injects/measures skill USE, `score` counts positive-application rate. Register it by appending to one list:

```python
# benchmarks/external/memory_modes/registry.py
MODES = [FactRecall(), PrecedentRecall(), ResumeTaskState(),
         GuardrailAdherence(), SkillAdherence()]   # <-- one line
```

The runner iterates `MODES`; the writer stamps `mode.name`; the schema already keys on `mode`. Because `guardrail_adherence` is itself built from a list of `RuleChecker` objects (see Mode 4), even a within-mode addition (a new banned-token rule) is a one-line append.

---

## 4. The six modes

All modes are **session-aware** (facts stored as real memories with `source_refs`, scoped via `MemoryScope`), and all report the per-mode metric **plus** a token-cost proxy per condition.

### 4.1 Mode `fact-recall`: similarity recall over stored facts

**Access pattern:** similarity recall over stored facts ("when did I paint the sunrise?", "do I already know this?"). This is RAG-over-memory done the way the first attempts did not: the transcript is **never** handed to the answerer, recall is **session-aware** (scoped, growing store), and the primary metric is **deterministic**. It answers the open question the honest findings left: a memory store loses to document RAG only when the full document is also in context; in the regime where history has scrolled out, recall over stored facts is the only path, and that is the regime this mode measures.

**(a) Population.** Corpus 1 is LoCoMo, parsed at **turn grain** (not flattened). For each sample (one user's history), each `session_N` becomes one artifact (`st.store(session_text, namespace=ns)`), and each dialogue turn becomes one memory:

```python
ns = f"factrecall-{sample_id}"
art = st.store(session_text, namespace=ns)                # real stele:// ref
scope = MemoryScope(namespace=ns, session_id=sess_n)
st.memory.add_many([
    AddRequest(
        text=f"[{t['speaker']}] {t['text']}",             # canonical assertion = the exact turn
        kind="fact",
        source_refs=[art.reference],                       # mandatory stele:// evidence
        scope=scope,
        summary=f"{t['speaker']} on {sess_dt}",            # tripartite: the observation
        detail=t["text"],                                  #            the supporting detail
        # action left None for plain facts
        metadata={"dia_id": t["dia_id"], "session": sess_n, "session_dt": sess_dt},
    )
    for t in conv[sess_n]
])
```

Turn grain is required because `dia_id` is the join key back to LoCoMo's `evidence` list, which makes a **judge-free retrieval metric** possible. `effective_from` is set to the real session timestamp (parsed deterministically with `dateutil`) so the same population is reusable by `resume-task-state`'s `as_of` checks without re-running.

Corpus 2 is `factrecall_synth`: a 30-fact inline fixture (first-person, dated, single-hop, each gold a single token/date/name) so the mode runs network-free and dataset-free in CI. Stored identically.

**(b) Task.** For each conversation, the agent is asked LoCoMo QAs that are deterministically checkable single-hop (cat-1) or temporal (cat-2) recalls, filtered to short golds (<=60 chars). Categories 3 (multi-hop, fuzzy gold), 4 (open-ended), and 5 (adversarial, already dropped by `_units`) are excluded. The query is the bare question; the agent gets **no transcript**.

**(c) Recall mechanic.** Session-aware similarity recall:

```python
hits = st.memory.search_with_score(q, MemoryScope(namespace=ns, session_id=None), limit=10)
ctx = "\n".join(h.record.summary or h.record.text for h in hits)
answer = _answer(ans, ctx, q)
```

**(d) Metric.**
- **`recall@K` (PRIMARY, deterministic):** `1` iff `set(evidence) ∩ {h.record.metadata["dia_id"] for h in hits[:K]} != ∅`. Pure set intersection, no model. Also report MRR via `sweep_matrix._rr` and `recall@1`. For the synthetic corpus, the join key is the fact index.
- **`exact_match` (SECONDARY, deterministic):** `normalize(gold) in normalize(answer)`, where `normalize` lowercases, strips punctuation, collapses whitespace, and canonicalizes dates with `dateutil` (so `7 May 2023`, `May 7, 2023`, `2023-05-07` compare equal). LoCoMo cat-1/cat-2 golds are atomic, so substring-after-normalize is sound.
- **`jscore` (OPTIONAL, off the critical path):** `rejudge_aw._jscore_correct` behind a `--judge` flag, reported only to measure the gap between the judge and deterministic `exact_match`. Never the headline.

**(e) Conditions.**

| Condition | Context to answerer | Isolates |
|---|---|---|
| `no_memory` | empty `""` | floor (near-zero for "when did *I*..." about a fictional user) |
| `prompt_stuffed` | the full session blob for that conversation | RAG/long-context ceiling; the token worst case |
| `prompt_stuffed_truncated` | stuffing capped at the model's window, oldest-first | the divergence point: at large conversations stuffing drops the gold turn |
| `memory_kw` | top-K from `search_with_score(memory_vector=False)` | tsvector recall |
| `memory_vec` | top-K from `search_with_score(memory_vector=True)` | RRF tsvector+pgvector recall (the opt-in leg) |

The two `memory_*` rows answer "does pgvector earn its keep" without a separate run. The headline result is the token-cost columns: as history grows, `prompt_stuffed` tokens scale linearly while `memory_*` stays flat at ~K turns, and once stuffing must truncate, memory-driven accuracy crosses above it.

**(f) Stele features.** `add_many` with tripartite `summary`/`detail` populated (`action` None); the mandatory evidence model (every memory cites a real `stele://` ref); session scope; the opt-in `memory_vector` RRF leg; `Stele.store` for the per-session artifact. Re-observation (`confirmations`/`evolved_confidence`) is logged as a diagnostic whenever a fact recurs across sessions. Not exercised here: supersession/`as_of` (that is `resume-task-state`), `action`/cq-kinds (that is `precedent`/`guardrail`), WorkGraph.

**(g) Token-cost.** Record `ctx_chars` and `ctx_tokens` (real `tiktoken cl100k_base` count if importable, else `ceil(chars/4)`; record which in `token_method`). Report per-condition mean tokens and the reduction ratio `memory_vec_tokens / prompt_stuffed_tokens`, plus `retr_ms`/`ans_ms`.

**Run:**
```bash
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele OPENAI_API_KEY=local \
  .venv/bin/python -m benchmarks.external.memory_modes.run --modes fact_recall --per-corpus 40
# deterministic, network-free smoke:
.venv/bin/python -m benchmarks.external.memory_modes.run --modes fact_recall --corpora factrecall_synth --per-corpus 30
```

### 4.2 Mode `precedent-recall`: similarity recall over task episodes

**Access pattern:** similarity recall, but the unit is a **prior task episode** ("Have I done something like this before? What tool, what result, where did it end up?"), not a sentence. The win condition is retrieving the *right past episode* and reading its tripartite fields: `summary` = what it was, `detail` = how it went / tools, `action` = the precomputed "what to DO next time." This is something RAG cannot do by construction: there is no source document in context; the episodes exist only because they were written to memory at the end of prior sessions. A no-memory agent has nothing to retrieve.

**(a) Population.** LoCoMo's QA shape does not fit "task episode," so this mode uses a **deterministic inline synthetic corpus**: 40 episodes across 8 recurring task types (5 each), so distractors are semantically adjacent (multiple "market-trends" episodes differing by quarter/segment). Each episode is one `memory.add`:

```python
scope = MemoryScope(namespace=ns)
ref = st.store(f"{ep.title}\n{ep.summary}\n{ep.detail}\nTOOL={ep.tool} "
               f"RESULT={ep.result} END_STATE={ep.end_state}", namespace=ns).reference
st.memory.add(
    text=ep.summary, kind="decision", source_refs=[ref], scope=scope,
    summary=ep.summary,   # WHAT it was
    detail=ep.detail,     # HOW it went / tools used
    action=ep.action,     # the precomputed WHAT-TO-DO
    metadata={"ep_id": ep.ep_id, "task_type": ep.task_type,
              "tool": ep.tool, "result": ep.result, "end_state": ep.end_state},
    confidence=1.0,
)
```

`kind="decision"` is a valid `MemoryKind`. `indexable_text` ranks on the tripartite fields, so recall discriminates on the structured view, which is the whole point of the mode.

**(b) Task.** One precedent query per episode, with `gold = (ep.tool, ep.result, ep.end_state)`. Queries are phrased to be answerable only from the episode's `detail`/`action`/metadata, never from generic knowledge.

**(c) Recall mechanic.** Cross-source similarity recall (`source_ref_filter=None`, because the point is to find *the relevant prior episode*):

```python
hits = st.memory.search_with_score(query, scope, limit=5)
top = hits[0].record if hits else None
ctx = _pack_episode(top)            # summary + detail + action, NOT the artifact body
answer = _answer(ans, ctx, query)
```

**(d) Metric.**
- **`precedent_hit@1` / `precedent_hit@5` (PRIMARY, deterministic):** `hits[k].record.metadata["ep_id"] == gold_ep_id`. No judge. `ep_id` is an exact string we control.
- **`triple_recall` (DETERMINISTIC, regex):** the answer contains all three distinctive gold tokens (`trend-scanner`, `bullish-payments`, `published`), checked with `\b`-anchored `re.search`.
- **`jscore` (SECONDARY, "soft"):** `_jscore_correct(judge, expected=f"{tool}; {result}; {end_state}", ...)`, reported but advisory only. Used to confirm coherent prose, not to decide correctness.

**(e) Conditions.**

| Lane | Context | Memory call |
|---|---|---|
| `no_memory` | `""` | none. Expected to abstain; floor |
| `prompt_stuffed` | all 40 episodes' `summary+detail+action` concatenated | none |
| `memory_keyword` | top-5 episodes, tripartite-packed | `memory_vector=False` |
| `memory_vector` | top-5 episodes, tripartite-packed | `memory_vector=True` (RRF) |

Hypothesis: `memory_*` matches or beats `prompt_stuffed` on `triple_recall` at a fraction of the tokens; `no_memory` floors near zero. A `--corpus-mult {1,2,3}` replicates the 8 task types into 80/120-episode corpora (more distractors), so the token-saving slope is measured, not asserted: at top-5 recall the saving vs stuffing is `5/N`, an ~8x context reduction at N=40 at equal accuracy.

**(f) Stele features.** Tripartite `summary`/`detail`/`action` (the precomputed "what to DO" is the recall payload); the opt-in pgvector leg; the evidence model (every episode cites `source_refs`). An optional `--reobserve` variant re-`add`s the gold episode's exact `summary` text once before querying, exercising the re-observation merge (asserting `confirmations==2` deterministically), proving re-observed precedents strengthen rather than duplicate. WorkGraph is **not** used here (it is `resume-task-state`'s lever).

**(g) Token-cost.** Per lane: `precedent_hit@1`, `precedent_hit@5`, `triple_recall`, `jscore (soft)`, `mrr`, `retr_ms`, `ans_ms`, `ctx_chars`, `ctx_tokens` (via `estimate_tokens`), `n`. The decisive comparison is `triple_recall` held roughly equal between `prompt_stuffed` and `memory_*` while `ctx_tokens` drops by `5/N`.

### 4.3 Mode `resume-task-state`: structured-state lookup

**Access pattern:** entity-keyed LATEST-STATE lookup + completion status, **NOT** similarity. This is where memory and RAG diverge hardest. RAG retrieves passages that look like the query; resume needs the *current truth about a named entity* ("feature X") even when the most recent transcript turn that mentions X is a half-finished thought. The answer is a function of *which assertion won* (supersession head) and *which subtasks are marked done* (WorkGraph node status). There is no relevant passage. This mode does not use the LLM judge for its primary metric: completion state is a closed set, checked programmatically.

It exercises two subsystems no other mode touches: the **supersession head** and the **WorkGraph**.

**(a) Population.** LoCoMo does not fit; the corpus is a deterministic inline `PROJECTS` list (~10 projects, ~40 queries total to match the n=40 elsewhere). Each project is a multi-session effort; each feature has an ordered event log and a `gold_status` drawn from the closed vocabulary `{done, in_progress, abandoned, absent}`. For each event, in order:

1. **Artifact:** `ref = st.store(event_text, namespace=ns, session_id=sess).reference`.
2. **Memory supersession head:** the latest state per feature is a memory atom whose new event supersedes the prior atom:
   ```python
   res = st.memory.add(
       text=f"{feature_id}: {status_phrase}", kind="decision",
       summary=f"feature {feature_id}", detail=event_text, action=next_step_phrase,
       source_refs=[ref], scope=scope, supersedes=prior_atom_id or None)
   prior_atom_id = res.record.id
   ```
   Tripartite here: `summary` = entity tag, `detail` = raw event, `action` = the precomputed next step the resume reads verbatim.
3. **WorkGraph node:** one `TaskNode` per feature, updated in place. `wg.add_node(TaskNode(..., label=feature_id, status="active", source_refs=[ref], ...))`; on the terminal event `wg.update_node(node_id, {"status": "done"})`.

Status mapping (resolved against the verified validator/model):
- `done` -> latest memory says "done"; node `status="done"`.
- `in_progress` -> latest memory says "pending/still"; node `status="active"`.
- `abandoned` -> latest memory says "decided NOT to build"; node `status="failed"` (a valid `NodeStatus`) and graph `status="abandoned"` (a valid `WorkGraphStatus`). Note: `validate_status_transition` permits a node `-> "abandoned"`, but `NodeStatus` does not list it. So the benchmark uses node `failed` + graph `abandoned` to stay inside both the validator and the type. This codebase inconsistency is logged as a follow-up, not worked around silently.
- `absent` -> no memory atom and no node for that feature_id.

Population is fully deterministic: fixed event order, fixed timestamps via a monotonic counter (`t0 + i*minute`) so `as_of` is reproducible.

**(b) Task.** The resume question verbatim ("where did we leave off on cart-merge?", "did we ever build gift-wrap?"). The agent must report current completion state, plus the next step for `done`/`in_progress`.

**(c) Lookup mechanic.** Entity-keyed, not similarity:

```python
# latest memory head, filtered by entity tag (deterministic, no embedding)
head = [m for m in st.memory.list(scope, status_filter=None, limit=1000)
        if m.summary == f"feature {feature_id}"]
# durable subtask completion from WorkGraph (latest-state, not search)
nodes = wg.query_graph(namespace=ns, query=feature_id, session_id=sess, active_only=False)
node_status = nodes[0].status if nodes else None
label = classify(head[0].text if head else None, node_status)  # -> {done,in_progress,abandoned,absent}
```

`memory.list(status_filter=None)` returns the newest-valid view (the store applies `effective_until IS NULL OR effective_until > now`), so superseded ancestors drop out and exactly the current head per feature survives. `head == []` <=> `absent`. The optional `as_of` sub-lane uses `wg.get_graph(gid, as_of=ts)` (SQLite store) + `memory.list(scope, as_of=ts)` to answer "what was the state at session 3?".

**(d) Metric.**
- **`state_accuracy` (PRIMARY, deterministic):** fraction where `classify(...)` equals `gold_status`. Closed 4-way vocabulary, exact key, pure function over the head + node status. 100% reproducible, no judge.
- **`false_state_rate` (deterministic):** fraction of `absent` queries where the condition asserts *any* concrete status. The hallucination rate. A similarity retriever returns the nearest feature and invents a status; the entity-keyed head returns `[]` and scores `absent`. This is the sharpest divergence test.
- **`phrasing_jscore` (OPTIONAL, judge-gated):** only for the memory-driven LLM-answer variant, confirming the natural-language resume agrees with gold. Reported, never the headline.

**(e) Conditions.**

| Condition | What it sees | How it answers |
|---|---|---|
| **no_memory** | only the single latest raw event line (a window that dropped the rest) | LLM answers from one line; `classify` over the answer. Misses terminal events that scrolled out; hallucinates on `absent`. |
| **prompt_stuffed** | the entire event log of the project (all sessions, raw) | LLM answers; `classify` over the answer. More correct than no_memory but pays full-history tokens and still drifts on `absent`/ordering. |
| **memory_driven** | the resolved head (`head.text`/`head.action`) + `node_status` for the one queried feature | programmatic `classify` (no LLM) on the primary path; optional LLM phrasing. Expected ~1.0 `state_accuracy`, ~0 `false_state_rate`, tiny token cost. |

This mode declares `conditions=("no_memory","prompt_stuffed","memory_driven")` but the honest regime (history exceeds window) is where `no_memory`/`prompt_stuffed` degrade; the runner already tolerates a mode dropping a condition if a 2-condition subset is preferred for the headline.

**(f) Stele features.** Supersession head (`add(supersedes=[...])` + `list(status_filter=None)`); tripartite (`summary` as entity key, `action` as the next step read verbatim); WorkGraph `TaskNode.status` + `query_graph(active_only=False)` + `update_node` guarded by `validate_status_transition`; `SQLiteWorkGraphStore` for the optional `as_of` sub-lane (the in-memory store raises `CapabilityError` on `as_of`); the evidence model (every atom/node cites `source_refs`).

**(g) Token-cost.** `ctx_tokens = estimate_tokens(context)` per `(condition, query)`: no_memory = one event line; prompt_stuffed = full event log (grows with history); memory_driven = `head.text + (head.action or "") + node_status` (flat, one line). Report `mean_ctx_tokens` and `token_reduction_pct = 1 - mean(memory)/mean(stuffed)`.

**Backend:** Postgres via `STELE_PG_DSN` (project default), `IndexingConfig(mode="skip")` (no chunk index needed). WorkGraph is **not** on the `Stele` facade, so the lane owns the store: `SQLiteWorkGraphStore("benchmarks/runs/cq-additive/resume-wg.sqlite")`, constructed directly exactly as `benchmarks/runtime.py` constructs its store.

### 4.4 Mode `guardrail-adherence`: enforcement, not recall

**Access pattern:** enforcement. The agent is given writing/coding tasks; stored memories are not facts to recall, they are *rules to obey*. The win condition is a falling **violation rate** measured by deterministic checkers, plus the **token cost** of carrying the rules. The honest-findings constraints are respected two ways: the metric is a regex/programmatic violation rate with **no LLM judge in the scoring loop**, and the corpus is a small deterministic synthetic rulebook. The LLM appears only as the *agent under test* (Qwen @ 193), never as the grader. The mode is itself a **family of pluggable `RuleChecker`s**: adding a rule is one dataclass instance plus one pure detector function.

**(a) Population.** A deterministic inline rulebook. Each rule is a `Rule(rule_id, kind, summary, detail, action, text, detect)` and is stored as one `memory.add`:

```python
scope = MemoryScope(namespace=ns, agent_id="writer")
rule_ref = st.store(RULEBOOK_TEXT, namespace=ns).reference
for r in RULES:
    st.memory.add(text=r.text, kind=r.kind, source_refs=[rule_ref], scope=scope,
                  summary=r.summary, detail=r.detail, action=r.action, confidence=1.0)
```

Seed corpus (8 deterministically-checkable rules; `kind` in `{instruction, pitfall, workaround}`):

| rule_id | kind | rule | `action` (injected) | `detect` |
|---|---|---|---|---|
| G-EMDASH | instruction | Never use em/en-dashes in prose | Replace with period, colon, comma, parens | `re.findall(r"[—–]", out)` |
| G-OXFORD | instruction | Always use the Oxford comma | In lists of 3+, comma before and/or | regex: 3-item list missing final comma |
| G-NOEMOJI | instruction | No emojis in any output | Strip all emoji | emoji unicode-range `findall` |
| G-PROHIB | pitfall | "leverage" is banned as a verb | Use "use" instead | `re.findall(r"\bleverage\b", out, re.I)` |
| G-UTILIZE | pitfall | Avoid "utilize" | Replace with "use" | `re.findall(r"\butiliz", out, re.I)` |
| G-SQLPARAM | workaround | Never build SQL with f-strings | Use parameterized queries | `re.search(r"f[\"'].*SELECT.*\{", out, re.I)` |
| G-TODO | pitfall | No TODO/FIXME in delivered code | Resolve/remove before delivering | `re.findall(r"\b(TODO\|FIXME)\b", out)` |
| G-HEADERCASE | instruction | Markdown headers use Title Case | Capitalize principal words in `#` headers | regex over `^#+ ` lines failing title-case |

Plus **22 inert distractor rules** (same shape, `detect = lambda out: []`) so selective recall is non-trivial and the token axis is meaningful: 30 rules stuffed vs ~2-4 relevant rules recalled. `source_refs=[rule_ref]` satisfies the evidence invariant.

**(b) Task.** ~20 writing/coding micro-tasks, each tagged with the `relevant_rules` it can violate (used only to score the right detectors and compute recall precision; never shown to the agent). Tasks are engineered so the base model has a measurable baseline tendency to violate (em-dashes especially).

**(c) Enforce mechanic + the ONE-correction sub-protocol.** Per task, the memory-driven condition recalls the relevant rules and injects their `action` payloads:

```python
hits = st.memory.search_with_score(task.prompt, scope, limit=4)
guard = "\n".join(f"- {h.record.summary}: {h.record.action}" for h in hits)
out = _answer_guarded(ans, guard, task.prompt)
```

The headline protocol (the brief's "violation rate before vs after ONE correction"):
1. **Round 0:** recall + enforce; measure violation rate.
2. For any rule that still fired, issue exactly **one correction**: `st.memory.add(text=..., kind="workaround", supersedes=[old_id], action=<sharper instruction>, ...)`. This exercises supersession. The corrected rule replaces the original, and `search_with_score` now surfaces the sharper `action`.
3. **Round 1:** re-run the same tasks; measure again.

A working enforcement layer drives `violations_round0 -> violations_round1` toward zero after one correction. `prompt_stuffed` cannot self-correct across a fresh session (nowhere durable to persist the fix), so it stays flat. That is the regime where memory diverges from prompt-stuffing.

Confirmation note: clean passes would naturally `confirm` a rule, but **there is no public `Memory.confirm`**. The public path is re-calling `add` with identical text+scope, which returns `MemoryAddResult(duplicate_of=...)` and increments `confirmations`. The benchmark records `result.record.confirmations`/`last_confirmed` to show the evidence model moving; it does not reach into `_store.confirm`.

**(d) Metric.**
- **`violation_rate` (PRIMARY, deterministic):** `violations(out, rule_ids) = {rid: len(RULE_BY_ID[rid].detect(out)) ...}`; `violation_rate = (# tasks with >=1 violation of a relevant rule) / (# tasks)`, per rule and aggregate. **No LLM judge**. Every `detect` is a regex/pure function. The judge endpoint is not called.
- **recall precision/recall of the memory layer (deterministic):** did `search_with_score` surface the task's `relevant_rules` in its top-k? Pure set math.
- **delta after one correction:** `round0_rate - round1_rate`.

A guardrail is a *syntactic* property of the output, exactly what regex checks well and what LLM judges check unreliably. Genuinely semantic rules (e.g. "is this passive voice?") are excluded from the scored set; `G-UTILIZE` is the lexical proxy for that family. `RuleChecker` is the pluggable seam.

**(e) Conditions.** Same `_QWEN` model, `temperature=0`, each task once per condition per round:

| condition | prompt | rules carried |
|---|---|---|
| **no_memory** | task only | 0 |
| **prompt_stuffed** | task + ALL 30 rules' `action` lines | 30 (8 real + 22 distractor) |
| **memory_driven** | task + top-k recalled rule `action`s | ~2-4 per task |

Sub-axis on memory-driven: `memory_vector in {False, True}`. Expected story: no_memory highest violation rate; prompt_stuffed and memory_driven both drive it down in round 0; memory_driven matches prompt_stuffed on violation rate at a fraction of the token cost; **only memory_driven keeps the gain after the one-correction round**.

**(f) Stele features.** Tripartite `action` as the injected enforcement payload (the canonical demonstration that `action` earns its column); the evidence model (`confirmations`/`last_confirmed` via re-`add`, `last_queried` advances on every `search_with_score`); cq lifecycle kinds (rules as `instruction`/`pitfall`/`workaround`; the correction writes a `workaround` that supersedes the original, a literal L1->L2 transition); supersession (`add(supersedes=[old_id])`, validated via `MemoryAddResult.superseded_ids`); the opt-in pgvector leg. An optional WorkGraph audit sub-lane records each task as a `TaskNode(kind="verification", status="done"|"failed")` citing the rule memory ref, scored by reading node statuses back via `query_graph`. Uses the SQLite store (the in-memory store rejects `as_of`).

**(g) Token-cost.** `estimate_tokens(guard)` per condition: no_memory = 0; prompt_stuffed = `O(R)` (here 30, scales linearly with the rulebook); memory_driven = `O(k)` (here ~4, constant in `R`). The deliverable plot is `guard_tokens vs rulebook_size R` at fixed violation rate: prompt_stuffed a line through the origin, memory_driven flat. Fully deterministic.

### 4.5 Mode `skill-adherence`: enforcement, positive polarity ("always do this")

A thin extension of §4.4: same `RuleChecker` family, same harness, opposite polarity. A skill is a learned positive habit (`kind="instruction"`), and the detector measures *application*, not violation.

**(a) Population.** Inline rulebook of positive skills, each with a deterministic application detector:

| rule_id | skill | `detect` (application = present) |
|---|---|---|
| S-PNPM | Use `pnpm`, never `npm`/`yarn`, in install commands | `re.search(r"\bpnpm (i\|install\|add)\b", out)` and no `\bnpm install\b` |
| S-OXFORD | Use the Oxford comma in 3+ lists | regex: final list item preceded by `, and/or` |
| S-CITE | Cite a `stele://` source when stating a stored fact | `re.search(r"stele://", out)` when the task asks for a sourced claim |
| S-TYPEHINT | Python function signatures carry type hints | `def f(...)` lines that include `:` annotations and `->` |

Plus distractor skills (`detect = lambda out: []`) so selective recall is non-trivial, identical to §4.4.

**(b-c) Task + mechanic.** Same as §4.4: tasks tagged with their `relevant_rules`; recall the relevant skills and inject their `action`. The only change is the scored direction.

**(d) Metric.** `application_rate` (PRIMARY, deterministic) = fraction of tasks where the relevant skill was applied. Plus the suggest-mode `surfaced_precision/recall` from §2.1. No LLM judge.

**(e) Conditions.** `no_memory` / `prompt_stuffed` / `memory_driven`, plus the suggest-vs-auto-accept sub-axis from §2.1. Story: memory_driven matches prompt_stuffed application at `O(k)` tokens.

**(f) Stele features.** Identical to §4.4; `action` is the injected positive instruction. The only delta from guardrail is `RuleChecker` polarity, which is why this is a 5th-mode plugin (§3.5), not a rewrite.

### 4.6 Mode `best-practice`: enforcement, suggested (never auto-forced)

The softest enforcement mode, and **suggest-only by construction** (no auto-accept setting; see §2.1). A best practice is an observation the system earned by watching outcomes, offered as advice.

**(a) Population.** Best practices stored as `kind="workaround"` or `summary`-kind memories whose `detail` carries the evidence ("sentence-aware chunking beat fixed-overlap in 5 of the last 5 runs") and `action` the suggestion. Seeded inline; deterministic.

**(b-c) Task + mechanic.** When a task matches a practice's trigger, recall surfaces it. There is **no enforcement path**: the agent (or operator) is shown the suggestion and chooses.

**(d) Metric.** `surfaced_recall` (PRIMARY, deterministic, §2.1): of the tasks where a relevant best practice exists, how often was it surfaced in the top-k. Optionally `take_up_rate` if a downstream chooser is simulated, but the headline is surfacing quality, because forcing is explicitly out of scope. No LLM judge.

**(e) Conditions.** `no_memory` (nothing surfaced) vs `memory_driven` (relevant practice surfaced). `prompt_stuffed` is omitted (stuffing every practice into the prompt is the anti-pattern this mode argues against); the runner already tolerates a 2-condition subset (§3.1).

**(f) Stele features.** Recall (`search_with_score`), the evidence model (`confirmations`/`last_confirmed` is exactly how a practice earns standing over repeated observation), and the suggest-not-force default. This mode is the cleanest demonstration that re-observation builds confidence: a practice confirmed 5 times outranks one seen once.

---

## 5. The reusable benchmark-to-blog workflow

A workflow that codifies the recurring session pattern: run mode A, run mode B, consolidate, write. Phases:

```
benchmark-to-blog
  Phase 1  RUN        : for each enabled mode, run it. Parallelizable: independent
                         namespaces, independent JSON, no shared mutable state.
                         Emits benchmarks/runs/cq-additive/multimode-<stamp>.json
                         (or one file per mode joined before Phase 2).
  Phase 2  CONSOLIDATE: merge every ModeReport into one additive results doc:
                         benchmarks/runs/cq-additive/Multimode-Results-<stamp>.md
                         (tables: mode x condition x {metric, ctx_tokens, n};
                         a "what we did / did NOT measure" block per mode, lifted
                         verbatim from each mode's `measured`/`not_measured`).
  Phase 3  DRAFT      : /gen-blog in the-yonk voice, fed ONLY the consolidated doc.
  Phase 4  REVIEW     : /not-an-ai inline review + honesty gates (below).
  Phase 5  WRITE      : ~/blogs/MM-DD-YYYY-slug.md.
```

**Parameters** (all defaulted): `enabled_modes` (default all four), `n` (default 40, honest small-n), `corpus` (default `locomo`; synthetic modes generate their own seeded corpora), `seed` (default 0), `persona` (default `the-yonk`), `output_dir` (default `~/blogs`), `results_dir` (default `benchmarks/runs/cq-additive`, never MEGA-GRID), `judge_mode` (default `deterministic-first`).

**Phase 1 parallelism:** modes share nothing (separate namespaces `memmode-<mode>-<corpus>`, separate JSON, separate WorkGraph temp dbs). Run concurrently, join before Phase 2. A failed mode is recorded in the consolidated doc and the run continues; partial results are publishable with sample sizes labeled.

**Honesty guards (hard gates. A violated guard fails the phase):**
1. **Label every sample size.** Phase 2 refuses to emit a table cell without an `n`. The existing posts already do this ("LoCoMo, n=40").
2. **Never fabricate numbers.** Phase 3 feeds gen-blog ONLY the consolidated `.md`. The draft is grep-checked: every numeric literal in the blog must appear in the results doc (author-computed ratios are allowed only when both operands appear in the doc. See open questions). A number not traceable to the doc fails Phase 4 and regenerates.
3. **Prefer deterministic metrics.** `resume_task_state` and `guardrail_adherence` are judge-free by construction; `fact_recall` and `precedent_recall` always carry `recall@K`/`mrr` so a judge-free number exists even when the J-score is flaky. When judge spread between runs is large, the doc calls it out.
4. **State what was and was NOT measured.** The blog MUST include the honesty box assembled from each mode's `not_measured` string (e.g. "fact_recall is single-doc QA where memory loses to RAG by design; this benchmark did not test cross-session carry-over end to end"). This mirrors the README distinction between payload-reduction claims and answer-accuracy claims.
5. **No em-dashes.** Phase 4 runs `/not-an-ai`; additionally a deterministic regex gate (`r"[—–]"` must return zero hits) blocks the Phase 5 write. This is the same `G-EMDASH` rule Mode 4 ships, reused as a publish gate. The workflow eats its own dog food.

This reflects how the session actually ran it: persona `the-yonk` (conversational, punchline-first, threes, parenthetical asides, the honesty tax), gen-blog -> not-an-ai -> `~/blogs/MM-DD-YYYY-slug.md`, results staged additively in `cq-additive/`. The existing posts already embody guards 1, 4, and 5; the workflow makes them mandatory instead of incidental.

### Recommendation: ship as workflow + code, not as a standalone skill

**Ship the benchmark orchestrator + Mode interface as code in the repo** (`benchmarks/external/memory_modes/`), not as a skill. It is deterministic Python that must live under version control, run in CI smoke tests (`tests/benchmarks_smoke/`), import the real `_units`/`_answer`/`_jscore_correct` helpers, and stay `mypy --strict`/`ruff` clean like the rest of `benchmarks/`. Registering a new mode is a `git`-reviewable diff, not a prompt edit.

**Ship the run -> consolidate -> blog -> review -> write pipeline as a `.claude/workflows/` workflow.** The phase graph (parallel fan-out in Phase 1, sequential gates after) is exactly what a workflow is for, and it *orchestrates other skills* (`/gen-blog`, `/not-an-ai`) rather than being one. The honesty guards are enforceable gates (regex checks, number-presence assertions) that a workflow can run between phases and fail on; a skill cannot reliably gate itself.

**Do not ship it as a standalone skill.** A skill would either duplicate gen-blog/not-an-ai (which it should call, not reimplement) or be a thin trigger the workflow already provides. The one optional seam is a thin `/benchmark-to-blog` launcher that parses args and invokes the workflow, purely for discoverability: a convenience launcher, not where the logic lives.

**Net:** Mode interface + orchestrator = repo code (testable, typed, CI-gated). The 5-phase pipeline with honesty gates = `.claude/workflows/benchmark-to-blog`. Optional `/benchmark-to-blog` skill = thin launcher only. The workflow's Phase 1 shells out to `python -m benchmarks.external.memory_modes.run --modes ...`; Phases 2-5 drive the existing content skills with the guards bolted on.

---

## 6. Build order

Build in this order, each slice leaving the tree compilable and the additive JSON valid:

1. **`guardrail-adherence` and `resume-task-state` first.** Both are **fully deterministic** (regex violation count; closed-vocabulary state classification) with **synthetic, inline, seeded corpora**. They need no LoCoMo cache, no judge, and minimal network (Qwen only for guardrail's agent-under-test; resume-task-state's primary metric needs no LLM at all). That makes them the fastest to land, the cheapest to run in CI smoke, and the most defensible headline numbers (no judge to flap). They also exercise the subsystems no other mode touches. Supersession + WorkGraph (resume) and enforcement + the one-correction supersession protocol (guardrail). So building them first validates the harness against the hardest plumbing early. Crucially, they are the modes where memory most clearly diverges from RAG, which is the whole thesis; proving the harness on the divergence cases first de-risks the narrative.
2. **`fact-recall` second.** It reuses the LoCoMo loader and answerer the prior lanes already proved, and its primary metric (`recall@K` on `dia_id`) is judge-free. It is the "RAG-over-memory done right" control: the second-most deterministic mode, but it depends on the LoCoMo cache and introduces the keyword-vs-vector sub-axis, so it lands after the two pure-synthetic modes.
3. **`precedent-recall` last.** It is the most synthetic-corpus-authoring-heavy (40 hand-authored episodes across 8 task types) and leans hardest on the J-score judge as a secondary signal. Its deterministic metrics (`precedent_hit@k`, `triple_recall`) are solid, but the corpus is the most work to get right and the mode is the least load-bearing for the core "memory != RAG" argument (it is a refinement of similarity-recall). It benefits from landing after `fact-recall` proves the similarity-recall conditions and the token-cost accounting.

4. **`skill-adherence` and `best-practice` ride on `guardrail-adherence`.** They reuse the §4.4 enforcement harness and `RuleChecker` family verbatim (§3.5), differing only in detector polarity and (for best-practice) being suggest-only. So they land immediately after mode `guardrail-adherence`, as the "fast follow" the brief calls for, before the LoCoMo-dependent and corpus-heavy similarity modes. Cost to add each: one corpus + one polarity flag, no runner change.

Rationale in one line: **deterministic-and-synthetic first (cheapest, most defensible, hardest plumbing), then the two enforcement-twin fast-follows, then deterministic-but-LoCoMo, then corpus-heavy-and-judge-leaning last.**

---

## 7. What we are NOT doing

- **Not another RAG-accuracy test.** The first attempts already measured single-document QA where the full document is in context, and memory lost (~0.10 vs ~0.65, n=40). That number is honest and stays in the honesty box, but it is the *baseline control*, not the headline. We are not re-running it as if a better recall config will flip it. In that regime it should not flip, and pretending otherwise would be dishonest. The modes here measure the regime where the document is *not* present.
- **Not re-litigating temporal.** LoCoMo category-5 (adversarial / "no answer" / temporal-unanswerable) is already dropped by `_units`, and we keep it dropped. `resume-task-state` does test time via `as_of`, but as a *structured-state* lookup ("state at session 3"), not as a temporal-reasoning QA category. We are not building a temporal-reasoning benchmark and not arguing about whether the model can infer dates.
- **Not an LLM-judge reliability study.** We measured the judge flapping 0.80 vs 0.22 and we respond by demoting it, not by studying it. The judge is a diagnostic column behind a flag; the headline never rides on it.
- **Not a cross-vendor comparison.** Per the project memory, cross-vendor LoCoMo/LongMemEval numbers are not apples-to-apples; only same-harness re-runs are defensible. Every number here comes from this harness against these endpoints, labeled with `n` and the pinned models.
- **Not touching MEGA-GRID.** All output is additive under `benchmarks/runs/cq-additive/`. The grid is the grid; these modes are a separate, additive artifact.

---

## 8. Open questions for the human

1. **fact-recall headline metric.** `recall@K` (judge-free, scores the memory engine's retrieval) vs `exact_match` (end-to-end, scores the agent's answer). The spec leads with `recall@K` because it is judge-free by construction; the brief's "deterministic-checkable dates/names" reads as end-to-end. Confirm which is the headline and which is the diagnostic.
2. **fact-recall framing vs LoCoMo person.** LoCoMo questions are third-person about fictional speakers ("When did Melanie paint a sunrise?"), not literally first-person "I." The synthetic corpus carries the true first-person framing. Confirm LoCoMo-as-proxy + synth-as-canonical is acceptable, or whether to rewrite a small first-person LoCoMo subset.
3. **pgvector memory leg prefetch.** `memory_vector=True` needs the bge embedder synthesized from `indexing.embed_model` even when `indexing.mode="skip"`. Confirm `scripts/chunkshop-setup.sh` is run in the bench environment so `memory_vec` does not silently fall back to keyword-only.
4. **WorkGraph not on the Stele facade.** `Stele` exposes only `memory`/`extract`/`recall`; there is no `Stele.workgraph` (verified). `resume-task-state` (and the optional guardrail audit sub-lane) must construct `SQLiteWorkGraphStore` directly, as `benchmarks/runtime.py` does. Confirm we keep it lane-owned rather than adding a facade property for this benchmark. If a facade accessor is planned, the modes should target that instead.
5. **The `abandoned` node-status inconsistency.** `validate_status_transition` permits a node `-> "abandoned"`, but `NodeStatus` does not list it (verified in `workgraph/models.py` vs `workgraph/validators.py`). The spec routes "abandoned" to node `status="failed"` + graph `status="abandoned"` to stay inside both. Confirm this mapping, and confirm whether the underlying code inconsistency should be filed as a separate stele issue.
6. **No public `Memory.confirm`.** The `Memory` class exposes `add/add_many/get/search/search_with_score/list/update/delete/retract` but not `confirm` (verified). The public confirmation path is re-`add` with identical text+scope (re-observation merge). Confirm the benchmarks go strictly through `add()` re-observation rather than reaching into the store's internal `confirm`.
7. **Synthetic corpora for a publishable benchmark.** `precedent-recall`, `resume-task-state`, and `guardrail-adherence` use hand-authored, seeded, inline corpora (no public dataset fits "prior task episode" / "enforce a rule" / "entity state over time"). Confirm hand-authored fixtures are acceptable for a publishable headline, or whether these should be sourced from real stele session traces (e.g. the WorkGraph event logs this project already produces) to blunt the "we wrote the test to pass" critique.
8. **Sample size for headline claims.** `precedent-recall` and `resume-task-state` are ~40 cases. Confirm n=40 is acceptable for a headline, or whether they should scale to match the n=250 / n=40 split used elsewhere in the grid for statistical comparability.
9. **Per-mode condition subsets vs table symmetry.** `resume-task-state` and `guardrail-adherence` legitimately lack an honest `prompt_stuffed` baseline in the regime memory is for (rules trivially fit; task history exceeds the window). Confirm the per-mode condition subset is acceptable, or whether you want a forced 3-condition matrix everywhere for table symmetry even when one column is degenerate.
10. **Number-presence grep guard strictness (workflow guard #2).** Should the guard allow author-computed ratios (e.g. "8x" from `5/40`, or "6x" from 0.10 vs 0.65) as long as both operands appear in the results doc, or require every literal to appear verbatim? The spec assumes the former.
11. **Judge-variance handling in the workflow.** When J-score spread between runs is large, should the workflow auto-suppress the judged metric from the headline and lead with `recall@K`/`mrr` instead, or just annotate the spread and let the-yonk decide in prose?
12. **guardrail one-correction baseline framing.** Should the round-1 re-run simulate a *fresh session* for `prompt_stuffed` (drop the correction from its prompt, sharply demonstrating it cannot persist a fix) or keep the correction in-prompt (more generous to the baseline)? The spec recommends the fresh-session framing but flags the choice.

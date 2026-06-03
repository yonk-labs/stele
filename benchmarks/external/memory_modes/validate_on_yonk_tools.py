# ruff: noqa: E501 -- validation helper.
"""Validate stele's memory functions against REAL, INDEPENDENT codebases.

The 6-mode benchmark lives next door and uses synthetic corpora plus this
project's own git history. That answers "can the engine do it?" It does not
answer "does it work on data the tool was not built around?" This script does:
it points the real Stele facade (memory.add, vector search_with_score, the
enforce loop) at real material mined from the OTHER ~/yonk-tools projects, all
of which were built in separate repos, and reports honest metrics.

Everything here is real and verbatim from those projects (READMEs, CLAUDE.md
rules, git subjects). The only curated part is the gold label, which is
self-evident (the project a fact describes, the commit a precedent points to,
zero violations for a guardrail).

Run:
    STELE_PG_DSN=postgresql://.../stele_bench \
      .venv/bin/python -m benchmarks.external.memory_modes.validate_on_yonk_tools

Recall sections need only the embedder (vector leg). The guardrail section needs
the answerer LLM; it degrades gracefully (skips) if the endpoint is unreachable.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.memory_modes.guardrail_adherence import _emdash
from benchmarks.external.memory_modes.run import _ANSWER_URL, _store
from benchmarks.external.sweep_matrix import _QWEN
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele

# --- REAL FACTS: project -> (purpose verbatim-ish, a question that should recall it) ---
# gold = the project. Questions deliberately avoid naming the project, so this is
# recall by meaning, not a name lookup. Several projects overlap (two do
# retrieval, two do summarization, two are off-prompt memory), which makes hit@1
# a genuinely hard discrimination test, not a gimme.
FACTS: tuple[tuple[str, str, str], ...] = (
    ("pg-raggraph", "GraphRAG on plain PostgreSQL: point it at documents, it chunks, embeds, extracts entities, no extra services", "which of my libraries does graph retrieval on plain Postgres with no extra services?"),
    ("lede", "Sub-millisecond extractive summarization with a stdlib core, plus structured fact extraction", "what is my sub-millisecond extractive summarizer?"),
    ("llm-judge", "Portable CLI for judging RAG and LLM benchmark runs across local, OpenAI-compatible, and cloud providers", "which tool grades benchmark runs across local and cloud LLM providers?"),
    ("pg-lexicon", "Postgres-backed metadata and semantic intelligence: crawls database schemas, profiles columns, mines real workload", "which service crawls database schemas and profiles columns?"),
    ("pg-synapse", "A Postgres-native agent-loop runtime in Rust that invokes LLM agents and tools", "what is my Rust agent-loop runtime built on Postgres?"),
    ("pocket_grader", "Local LLM-assisted test grading: upload a test plus student submissions and grade them", "which tool grades student test submissions locally with an LLM?"),
    ("chunkshop", "A small, standalone, embeddable ingestion tool that pulls text from a source and chunks it", "which tool is my standalone embeddable text-ingestion library?"),
    ("yonk-robo-codemonkey", "Local-first MCP server that indexes code and documentation into Postgres with pgvector for hybrid retrieval", "which MCP server indexes my code and docs for hybrid retrieval?"),
    ("pg-agent", "A PostgreSQL extension that makes AI agents a database-native primitive instead of an external service", "which tool makes AI agents a native Postgres primitive?"),
    ("pgrx", "A framework for developing PostgreSQL extensions in Rust, idiomatic and safe", "what framework builds Postgres extensions in Rust?"),
    ("skimr-neural", "CPU-only neural abstractive summarization companion to the extractive summarizer", "which tool does CPU-only neural abstractive summarization?"),
    ("yonk-taskstash", "Off-prompt memory for LLM apps: keep large or sensitive data out of the context window", "which tool keeps large or sensitive data out of the LLM context window?"),
)

# --- REAL COMMIT EPISODES (verbatim subjects) and PRECEDENT QUERIES (gold = sha) ---
# The store holds many real commits as distractors; each query is a paraphrase
# of a real task, never the subject verbatim.
COMMITS: tuple[tuple[str, str, str], ...] = (
    ("b8dd415", "pg-raggraph", "fix(packaging): drop git dep from ab-gate extra so PyPI accepts the upload"),
    ("012669d", "pg-raggraph", "bench(rrf): scale A/B on full MuSiQue (1700 docs) with rank-sensitive metrics"),
    ("09ac700", "pg-raggraph", "test(rrf): hybrid correctness assertion + real hybrid A/B (LLM-built graph)"),
    ("4ce30a7", "chunkshop", "docs: add bge-large data point, RETRACT the headroom hypothesis"),
    ("e7a1bd2", "chunkshop", "docs: correct 'threads are free' claim, threads trade against CPU headroom"),
    ("b5a5862", "chunkshop", "chore(release): v0.8.2 search/ingest performance + tests"),
    ("f555d1a", "extractive_summary", "release: v0.3.0 rename skimr to lede"),
    ("ec381a8", "extractive_summary", "chore(pypi): publishing infrastructure + packaging fixes"),
    ("04987a9", "lede", "release: v0.4.5 structured report metadata"),
    ("848d0e0", "lede", "fix(pins): guarantee all supplied headings survive"),
    ("7789191", "pocket_grader", "feat: add per-student Word report builder"),
    ("c2686d5", "pocket_grader", "feat: add needs_review resolution queue, finalization gate, grading-failure handling"),
    ("a42c15f", "pocket_grader", "feat: add FastAPI app, templates, and end-to-end flow"),
    ("5b60282", "pg-agent", "feat(nl2sql): error-feedback retry + plausibility + tier-3 eval infra"),
    ("399951c", "pg-agent", "fix(eval): extract SQL from JSON-candidates + strip training comments"),
    ("660a0d7", "skimr-neural", "scope(v0.0.1): cut bert plugin, single-plugin llm-only release"),
    ("53cc7df", "skimr-neural", "feat(llm): chat-template prompt prefill + tighten token budget (30x latency win)"),
    ("cd67538", "pg-synapse", "ci(clippy): exclude pg_synapse_pgrx from cargo clippy --workspace"),
    ("bbc8432", "pg-lexicon", "feat(spF3): add context package CLI and golden fixtures"),
    ("842c60c", "pg-lexicon", "chore(spF4): Phase F complete"),
    ("664cd8d", "compare_models", "feat: add chunking module with paragraph-boundary splitting and ctx-aware sizing"),
    ("7912b46", "compare_models", "feat: retroactive rejudging + updated benchmark report with quality scores"),
)
PRECEDENTS: tuple[tuple[str, str], ...] = (
    ("have I had a PyPI upload rejected and had to fix a packaging dependency?", "b8dd415"),
    ("have I retracted a benchmark hypothesis after new data came in?", "4ce30a7"),
    ("have I scaled an A/B retrieval benchmark on a large multi-hop dataset?", "012669d"),
    ("have I renamed a project as part of a release?", "f555d1a"),
    ("have I built a per-student report generator?", "7789191"),
    ("have I added error-feedback retry to a text-to-SQL pipeline?", "5b60282"),
    ("have I cut a plugin to ship a smaller single-plugin release?", "660a0d7"),
    ("have I excluded a crate from the clippy workspace in CI?", "cd67538"),
    ("have I built a context-package CLI with golden fixtures?", "bbc8432"),
    ("have I corrected a wrong claim about threads being free?", "e7a1bd2"),
)


def _no_gpt4o(text: str) -> int:
    """Naive: any mention of gpt-4o. WRONG for a selection rule, kept to show why:
    the repair step says 'use X instead of GPT-4o', which this flags as a
    violation even though the model is correctly avoiding it. Backfires under
    enforcement (the run proves it)."""
    return len(re.findall(r"gpt-?4o", text, re.IGNORECASE))


_AVOID = ("avoid", "instead of", "rather than", "not ", "never", "no gpt", "don't", "do not", "without")


def _chose_gpt4o(text: str) -> int:
    """Semantic: flag gpt-4o only when it is RECOMMENDED, not when it is named
    while being avoided. Matches the rule's intent (don't SELECT it), which a
    surface substring scan cannot. The right production answer is to check the
    chosen-model field, not prose; this negation-aware scan is the cheap version."""
    hits = 0
    for m in re.finditer(r"gpt-?4o", text, re.IGNORECASE):
        prefix = text[max(0, m.start() - 40):m.start()].lower()
        if any(cue in prefix for cue in _AVOID):
            continue
        hits += 1
    return hits


# --- REAL guardrails (verbatim from the projects) + tasks that tempt them ---
# (rule_id, domain, summary, fix, detector, [tasks])
_GPT4O_TASKS = (
    "Name the single best OpenAI model for a coding agent that writes SQL, one short sentence.",
    "Recommend the strongest general-purpose model for an agent in one sentence.",
    "Which model should I default to for a high-accuracy reasoning agent? One sentence.",
)
GUARDRAILS = (
    ("no-gpt4o-naive", "pg-agent: gpt-4o is outdated, use gpt-5-mini (naive substring checker)",
     "gpt-4o is outdated; use gpt-5-mini instead", _no_gpt4o, _GPT4O_TASKS),
    ("no-gpt4o-semantic", "pg-agent: gpt-4o is outdated, use gpt-5-mini (semantic checker)",
     "gpt-4o is outdated; use gpt-5-mini instead", _chose_gpt4o, _GPT4O_TASKS),
    ("no-emdash", "my standing rule: never use em-dashes or en-dashes",
     "Use a period, comma, colon, or parentheses instead of a dash", _emdash, (
         "Write two sentences about why benchmarks matter, with a dramatic aside in the middle.",
         "Write one sentence giving a numeric range with a parenthetical clarification.",
         "Write a punchy marketing line with a dramatic pause before the payoff.",
     )),
)


def validate_recall(stele: Stele, complete: Callable[[str], str] | None = None) -> None:
    print("\n=== FACT RECALL on real project purposes (vector, strict hit@1) ===")
    ns = "validate-yonk-facts"
    scope = MemoryScope(namespace=ns)
    for proj, purpose, _q in FACTS:
        ref = str(stele.store(purpose, namespace=ns).reference)
        stele.memory.add(text=purpose, kind="fact", source_refs=[ref], scope=scope,
                         summary=purpose, metadata={"project": proj})
    hits = 0
    for proj, _purpose, q in FACTS:
        got = stele.memory.search_with_score(q, scope, limit=1)
        top = got[0].record.metadata.get("project") if got else None
        ok = top == proj
        hits += ok
        print(f"  [{'OK ' if ok else 'MISS'}] {q[:58]:<58} -> {top or '(none)'}")
    print(f"  hit@1 = {hits}/{len(FACTS)} = {hits/len(FACTS):.2f}")

    print("\n=== PRECEDENT RECALL on real commit episodes (vector, strict hit@1) ===")
    ns2 = "validate-yonk-precedent"
    scope2 = MemoryScope(namespace=ns2)
    for sha, proj, subject in COMMITS:
        ref = str(stele.store(subject, namespace=ns2).reference)
        stele.memory.add(text=subject, kind="decision", source_refs=[ref], scope=scope2,
                         summary=subject, detail=f"{proj}: {subject}", metadata={"sha": sha})
    hits = 0
    for q, gold in PRECEDENTS:
        got = stele.memory.search_with_score(q, scope2, limit=1)
        top = got[0].record.metadata.get("sha") if got else None
        ok = top == gold
        hits += ok
        print(f"  [{'OK ' if ok else 'MISS'}] {q[:58]:<58} -> {top or '(none)'} (gold {gold})")
    print(f"  hit@1 = {hits}/{len(PRECEDENTS)} = {hits/len(PRECEDENTS):.2f}")


def _enforce(complete: Callable[[str], str], summary: str, fix: str,
             detect: Callable[[str], int], task: str, rounds: int = 2) -> str:
    base = f"RULE: {summary}. {fix}.\n\nTASK: {task}"
    out = complete(base)
    for _ in range(rounds):
        n = detect(out)
        if n == 0:
            return out
        out = complete(f"{base}\n\nYOUR PREVIOUS ANSWER:\n{out}\n\nThat broke the rule "
                       f"({n} times). Rewrite it so the rule holds. {fix}. Output only the corrected text.")
    return out


# --- Rung 3: a structural gate for the gpt-4o SELECTION rule. ---
# The rule is a VERSION POLICY, not a blanket ban: gpt-4o is outdated, use
# gpt-5-mini (the current small OpenAI model). A correct gate must REMEDIATE
# IN-FAMILY. Substituting a different vendor (e.g. claude-opus) trades a banned
# choice for an UNREACHABLE one: wrong provider, needs a different key, and it
# defeats the point when the whole context is OpenAI. So the gate maps the
# deprecated value to its current equivalent; it does not pick an arbitrary model.
_DENY = re.compile(r"gpt-?4o", re.IGNORECASE)
_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_DENY, "gpt-5-mini"),  # gpt-4o is outdated -> current small OpenAI model, same provider
)


def _gate_choice(chosen: str) -> tuple[str, bool]:
    """Validate a chosen model and remediate in-family. Returns
    (final_model, was_remediated). Maps a deprecated model to its current
    equivalent rather than substituting an unreachable cross-vendor model."""
    for pat, current in _REPLACEMENTS:
        if pat.search(chosen):
            return current, True
    return chosen.strip(), False


def validate_selection_gate(stele: Stele, complete: Callable[[str], str]) -> None:
    print("\n=== gpt-4o (outdated) -> gpt-5-mini via a STRUCTURAL GATE (rung 3, deterministic) ===")
    pre = post = 0
    for task in _GPT4O_TASKS:
        chosen = complete(f"{task} Reply with ONLY the model name, nothing else.")
        final, fixed = _gate_choice(chosen)
        pre += 1 if _DENY.search(chosen) else 0
        post += 1 if _DENY.search(final) else 0
        print(f"  model chose '{chosen[:30]}' -> gate {'REMAPPED -> ' + final if fixed else 'allowed'}")
    n = len(_GPT4O_TASKS)
    print(f"  pre-gate violations={pre}/{n}  post-gate violations={post}/{n} (deterministic, in-family remediation)")


def validate_guardrails(stele: Stele, complete: Callable[[str], str]) -> None:
    print("\n=== GUARDRAIL enforcement on real rules (inject vs check+repair) ===")
    for _rid, summary, fix, detect, tasks in GUARDRAILS:
        inj_viol = enf_viol = 0
        for task in tasks:
            injected = complete(f"RULE: {summary}. {fix}.\n\nTASK: {task}")
            inj_viol += 1 if detect(injected) > 0 else 0
            enforced = _enforce(complete, summary, fix, detect, task)
            enf_viol += 1 if detect(enforced) > 0 else 0
        n = len(tasks)
        print(f"  {summary[:46]:<46} inject_violation={inj_viol}/{n}  enforced_violation={enf_viol}/{n}")


def main() -> int:
    dsn = os.environ.get("STELE_PG_DSN")
    if not dsn:
        raise SystemExit("set STELE_PG_DSN")
    stele = _store(dsn, memory_vector=True)
    complete: Callable[[str], str] | None = None
    try:
        ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_QWEN,
                                   base_url=_ANSWER_URL, api_key="local")
        complete = lambda p: str(ans._chat(model=_QWEN, json_mode=False,  # noqa: E731
                                           messages=[{"role": "user", "content": p}])).strip()
        complete("ping")  # probe the endpoint
    except Exception as e:  # noqa: BLE001
        print(f"(answerer unreachable: {e}; running recall-only)", file=sys.stderr)
        complete = None

    validate_recall(stele)
    if complete is not None:
        validate_guardrails(stele, complete)
        validate_selection_gate(stele, complete)
    else:
        print("\n=== GUARDRAIL enforcement: SKIPPED (no answerer) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

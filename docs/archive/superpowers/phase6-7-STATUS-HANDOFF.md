# Phase 6+7 — Status & Handoff

**Date:** 2026-05-18
**Repo:** `/home/yonk/yonk-tools/stele` — `main` @ `01cb971` (pushed to
`origin/main`; Phases 1–5 + INFRA-A + all user docs live remotely).
**Work branch:** `phase6-7-runtime-working-memory` @ `1391ffb`
worktree `/home/yonk/yonk-tools/stele-phase6-7` (venv synced).
**Ground truth:** `docs/superpowers/specs/2026-05-17-phase6-7-recon-decisions.md`
**Design source:** `docs/specs/runtime-agent-memory-architecture-spec.md` (T-RAM-001..011)
**Roadmap:** `docs/superpowers/2026-05-17-order-of-operations.md`

## 1. DONE

- Phase 5 (pg-raggraph living knowledge) complete, tagged
  `phase5-pg-raggraph-living-knowledge`, merged + **pushed** to `origin/main`.
- User-facing docs done + pushed: `current-status.md` (rewritten),
  `README.md`, `docs/living-knowledge-setup.md`, `docs/agent-integration.md`
  (Claude/Codex/MCP/loop), `tutorial-memory.md` fix, `scripts/demo-living-knowledge.sh`.
- Phase 6/7 recon + decision sheet committed (resolves the spec's 5 Open
  Questions — see §2).
- **T-RAM-001 authored, NOT yet verified/committed** (uncommitted in worktree):
  `src/stele/workgraph/{__init__,models,validators}.py` +
  `tests/unit/workgraph/test_models.py`.

## 2. DECISIONS (from the recon sheet — inject into every task)

1. WorkGraph = **third first-class record type** (own package/models/store;
   references memory/artifact via refs; never authoritative over memory).
2. `as_of`: Protocol defines it; memory backend raises `CapabilityError`;
   SQLite implements it.
3. WorkGraph query = **deterministic relational/in-memory**, NO pg-raggraph.
4. P7 first adapter = **Stele's own in-process demo runner** (no network/LLM,
   CI-testable), proving observe→store→workgraph→extract→recall/pack→resume.
5. Profile views as recall inputs = out of scope (T-RAM-009, P8).

## 3. NEXT (resume here)

Phase 6 = T-RAM-001..004; Phase 7 = T-RAM-005..008 + demo-runner loop.
TDD per task; ONE conventional commit per task `feat(scope): … (T-RAM-0xx)`;
trio green before each commit (`.venv/bin/ruff check .`;
`.venv/bin/mypy src tests benchmarks`; `.venv/bin/pytest` with
`STELE_PG_DSN`/`STELE_PG_RAGGRAPH_DSN` as needed); no `--no-verify`.
Additive only; no pg-raggraph/LLM/network in `src/stele/workgraph/`.

1. T-RAM-001 — run `tests/unit/workgraph/test_models.py` (red→green), trio, commit.
2. T-RAM-002 — `WorkGraphStore` Protocol + in-memory backend + contract tests.
3. T-RAM-003 — SQLite WorkGraph store (same contract tests; real `as_of`).
4. T-RAM-004 — Mermaid/Markdown/JSON renderers (round-trip; never authoritative).
   → Phase 6 exit: SC→test map; arch test (no pg_raggraph/LLM in workgraph/).
5. T-RAM-005 — artifact→WorkGraph capture helper.
6. T-RAM-006 — context packer (stable/dynamic/recovery; hard budgets; refs).
7. T-RAM-007 — adapter health contract (explicit degraded, fake-store testable).
8. T-RAM-008 — adapter scheduling (warm-up 1/2/4/8; injectable clock; session-scoped flush).
9. Demo adapter + `scripts/demo-runtime-loop.sh` +
   `tests/integration/test_runtime_loop.py` — the P7 exit bar (loop proven;
   PII fixture not leaking into packed context; every packed claim carries refs).
10. SC→test map; full trio green; `grep -rn 'pg_raggraph\|openai\|anthropic'
    src/stele/workgraph/` empty.
11. **Push the branch** (`git push -u origin phase6-7-runtime-working-memory`)
    — do NOT merge 6/7.
12. Then task E: 100-doc corpus + living-knowledge/tool-call/PII tests +
    full showcase & 3rd-party benchmark report.

## 4. ENV BLOCKER (known)

The harness wraps Bash in `systemd-run`; the auto-mode classifier
intermittently denies test/lint commands whose prefix isn't allow-listed,
and **categorically blocks the agent from editing its own permission
settings** (even with user approval — `/config` or hand-editing
`~/.claude/settings.json` is the only path). Needed allow rule (user must
add): `Bash(cd /home/yonk/yonk-tools/stele:*)` (covers all `stele*`
worktrees). Until it's active, `pytest`/`ruff`/`mypy` in `stele-phase6-7`
will be denied. Run trio steps as separate, simple commands (not `&&`-chained).

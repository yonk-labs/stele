# ruff: noqa: E501,SIM115  -- benchmark consolidation.
"""Consolidate every benchmark lane (stele + competitors) into ONE mega grid: MD + CSV.

Reads the stele sweep matrix (26 lanes x jscore/mrr/tokens/latency) and the competitor
result JSONs (Mem0 local, Mem0 gpt-5-mini, Letta archival, Letta agent), aggregates
each to per-(system, lane, corpus) metrics, and writes:
  benchmarks/runs/cross-corpus/MEGA-GRID.md   (human-readable, grouped by corpus)
  benchmarks/runs/cross-corpus/MEGA-GRID.csv   (load into Excel)

Metrics: jscore | mrr | ~tokens (ctx_chars/4) | retr_ms | ans_ms | n. Competitor MRR is
N/A where memories are abstractive (Mem0 rewrites facts). Run after the token re-runs land.
"""
from __future__ import annotations

import csv
import glob
import json
from pathlib import Path
from statistics import mean

_ROOT = Path("benchmarks/runs/cross-corpus")
_CORPORA = ["locomo", "ragbench-hotpotqa", "ragbench-covidqa"]

# Lexicon prepended to MEGA-GRID.md so the codenames are self-explaining (a jr dev
# should be able to read a row without spelunking the scripts). Keep in sync with
# testing/results/MEGA-GRID.md and testing/results/reading-the-grid.md.
_KEY = """## How to read this grid

Each row is one **recipe** (a "lane") run against one **corpus**, scored on the same
questions by the same judge. Higher `jscore` = more right answers; lower `~tokens` =
cheaper context. The only hard part is decoding the lane name — it's shorthand for a
few choices.

### `system` — who produced the row

| name | what it is |
|---|---|
| `stele-highN` | stele, the **confident** runs (n≈250). These are the numbers to trust. |
| `stele-sweep` | stele, a wide **exploratory** sweep (n=40). Directional only — small samples flip. |
| `letta-archival` | Letta (a competitor) in its archival-memory mode. |
| `letta-agent` | Letta in agent mode — an **interrupted** n=20 run that scored 0.00. Kept as a record, *not* a fair number. |
| `mem0-local` | Mem0 (a competitor), using a local LLM to boil docs down to atomic facts. |
| `PARAMETRIC-FLOOR` | The control: answer with **no memory at all**. Whatever the model scores here it already knew — subtract it before believing any row. |

### `lane` — the recipe

A lane name encodes **chunker -> retrieval -> packing** (plus a couple of knobs).

**Chunker** (how a doc is sliced before indexing): `sentence_aware` = sentence boundaries,
~1000 chars (default) · `fixed_overlap` = blind fixed windows · `consolidation` /
`enriching` = squeeze the doc into extracted facts.

**Retrieval** (how chunks are picked per question): `hybrid` = vector + keyword fused via
RRF (default) · `keyword` = full-text only (the *old* default — note how close it sits to
the floor) · `cascade_a` = keyword-first then vector re-rank · `cascade_b` = vector-first
then keyword re-rank · `raw_fetch` = skip retrieval, feed the whole document (ceiling).

**Packing** (how chunks are formatted for the model): `raw` = verbatim · `digest` =
query-focused summary + top-5 chunks · `facts` = digest + extracted fact list ·
`digest_mix` = digest + facts + top-3 raw chunks (kitchen sink).

**Knobs:** `hnsw` = approximate vector index (default) vs `exact` = brute-force scan ·
`nb1`/`nb0` = neighbor window on/off · `k=N` = how many chunks were fed. So
`hybrid_raw_hnsw` = the default recipe, `nb0_k=10` = neighbor off / top-10,
`A:sentence_aware+facts` = sweep family A, `(memory)` = a competitor's own single lane.

### Columns

`jscore` = fraction the judge marked correct (gemma-4-26B, **abstention = wrong**), 0-1 ·
`mrr` = how near the top the right chunk ranked, 1/rank averaged (stele-only; competitor
memories are abstractive -> `—`) · `~tokens` ≈ ctx_chars/4 (cost axis) · `retr_ms` /
`ans_ms` = retrieval / answer latency · `n` = questions in that cell.
"""


def _latest(pattern: str) -> str | None:
    fs = sorted(glob.glob(str(_ROOT / pattern)))
    return fs[-1] if fs else None


def _tok(chars: float) -> int:
    return int(chars / 4)


def _agg_rows(rows: list[dict], corpus: str | None) -> dict | None:
    rs = [r for r in rows if "correct" in r and (corpus is None or r.get("corpus") == corpus)]
    if not rs:
        return None
    has_tok = [r for r in rs if "ctx_chars" in r]
    return {
        "jscore": round(mean(r["correct"] for r in rs), 3),
        "tokens": _tok(mean(r["ctx_chars"] for r in has_tok)) if has_tok else None,
        "retr_ms": round(mean(r["retr_ms"] for r in has_tok), 1) if has_tok else None,
        "ans_ms": round(mean(r["ans_ms"] for r in has_tok), 1) if has_tok else None,
        "mrr": None,
        "n": len(rs),
    }


def _best(pattern: str) -> list[dict] | None:
    """Among all matching JSONs, pick the run with the most token-instrumented rows
    (the high-N re-runs) — robust to stale per-75 files sharing the naming."""
    best, best_score = None, -1
    for fp in glob.glob(str(_ROOT / pattern)):
        rows = json.load(open(fp)).get("rows", [])
        score = sum(1 for r in rows if "ctx_chars" in r) * 10000 + len(rows)
        if score > best_score:
            best, best_score = rows, score
    return best


def main() -> None:
    grid: list[dict] = []  # each: system, lane, corpus, jscore, mrr, tokens, retr_ms, ans_ms, n

    # --- stele sweep (26-lane breadth, n=40) ---
    sweep = _latest("sweep-matrix-*.json")
    if sweep:
        agg = json.load(open(sweep))["agg"]
        for corpus in _CORPORA:
            for lane, m in agg.get(corpus, {}).items():
                grid.append({"system": "stele-sweep", "lane": lane, "corpus": corpus,
                             "jscore": m["jscore"], "mrr": m["mrr"], "tokens": _tok(m["ctx_chars"]),
                             "retr_ms": m["retr_ms"], "ans_ms": m["ans_ms"], "n": m["n"]})

    # --- stele high-N (6 key lanes + exact-vs-HNSW, n=250) ---
    hn = _latest("high-n-matrix-*.json")
    if hn:
        agg = json.load(open(hn))["agg"]
        for corpus in _CORPORA:
            for lane, m in agg.get(corpus, {}).items():
                grid.append({"system": "stele-highN", "lane": lane, "corpus": corpus,
                             "jscore": m["jscore"], "mrr": m["mrr"], "tokens": m["tokens"],
                             "retr_ms": m["retr_ms"], "ans_ms": m["ans_ms"], "n": m["n"]})

    # --- stele high-N digest lane (ran separately; completes raw/digest/facts) ---
    dig = _latest("digest-highn-*.json")
    if dig:
        rows = json.load(open(dig)).get("rows", [])
        for corpus in _CORPORA:
            m = _agg_rows([r for r in rows if r.get("corpus") == corpus], corpus)
            if m:
                # _agg_rows leaves mrr None; recompute from rows that carry it
                crows = [r for r in rows if r.get("corpus") == corpus and "mrr" in r]
                m["mrr"] = round(mean(r["mrr"] for r in crows), 3) if crows else None
                grid.append({"system": "stele-highN", "lane": "hybrid_digest_hnsw", "corpus": corpus, **m})

    # --- stele high-N digest VARIANTS (digest+expanded-hints, enriching+digest/facts) ---
    for src in ("digest-variants-highn-*.json", "topk-sweep-*.json"):
        fp = _latest(src)
        if not fp:
            continue
        a = json.load(open(fp)).get("agg", {})
        for corpus in _CORPORA:
            for lane, m in a.get(corpus, {}).items():
                grid.append({"system": "stele-highN", "lane": lane, "corpus": corpus,
                             "jscore": m["jscore"], "mrr": m.get("mrr"), "tokens": m.get("tokens", 0),
                             "retr_ms": m.get("retr_ms"), "ans_ms": m.get("ans_ms"), "n": m.get("n", 0)})

    # --- no-context parametric floor (the baseline to subtract from each score) ---
    floor = _latest("no-context-floor-*.json")
    if floor:
        t = json.load(open(floor))["tally"]
        for corpus in _CORPORA:
            if corpus in t and t[corpus]["n"]:
                grid.append({"system": "PARAMETRIC-FLOOR", "lane": "(no context)", "corpus": corpus,
                             "jscore": round(t[corpus]["ok"] / t[corpus]["n"], 3), "mrr": None,
                             "tokens": 0, "retr_ms": None, "ans_ms": None, "n": t[corpus]["n"]})

    # --- competitors (pick the best-instrumented / highest-N run per system) ---
    comp = [
        ("mem0-local", _best("mem0-lane-*.json"), _CORPORA[1:]),
        ("mem0-local", _best("mem0-locomo-turns-*.json"), ["locomo"]),
        ("letta-archival", _best("letta-lane-*.json"), _CORPORA),
        ("letta-agent", _best("letta-agent-*.json"), _CORPORA),
    ]
    for system, rows, corpora in comp:
        if not rows:
            continue
        for corpus in corpora:
            agg = _agg_rows(rows, None if corpus == "locomo" and not any("corpus" in r for r in rows) else corpus)
            if agg:
                grid.append({"system": system, "lane": "(memory)", "corpus": corpus, **agg})

    # --- CSV ---
    cols = ["system", "lane", "corpus", "jscore", "mrr", "tokens", "retr_ms", "ans_ms", "n"]
    with open(_ROOT / "MEGA-GRID.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in sorted(grid, key=lambda r: (r["corpus"], -r["jscore"])):
            w.writerow({c: row.get(c, "") for c in cols})

    # --- Markdown ---
    md = ["# Mega benchmark grid — every lane x corpus (post-fix)\n", _KEY]
    for corpus in _CORPORA:
        md.append(f"\n## {corpus}\n")
        md.append("| system | lane | jscore | mrr | ~tokens | retr_ms | ans_ms | n |")
        md.append("|---|---|---|---|---|---|---|---|")
        for r in sorted([g for g in grid if g["corpus"] == corpus], key=lambda r: -r["jscore"]):
            md.append(f"| {r['system']} | {r['lane']} | {r['jscore']:.2f} | "
                      f"{r['mrr'] if r['mrr'] is not None else '—'} | "
                      f"{r['tokens'] if r['tokens'] is not None else '—'} | "
                      f"{r['retr_ms'] if r['retr_ms'] is not None else '—'} | "
                      f"{r['ans_ms'] if r['ans_ms'] is not None else '—'} | {r['n']} |")
    (_ROOT / "MEGA-GRID.md").write_text("\n".join(md) + "\n")

    print(f"wrote {_ROOT}/MEGA-GRID.md and MEGA-GRID.csv  ({len(grid)} rows)")
    systems = sorted({g["system"] for g in grid})
    for s in systems:
        n_rows = len([g for g in grid if g["system"] == s])
        print(f"  {s}: {n_rows} lane-rows")


if __name__ == "__main__":
    main()

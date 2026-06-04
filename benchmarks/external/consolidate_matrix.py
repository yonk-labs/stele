"""Consolidate the overnight model-matrix into one results doc.

Reads every stele answer-workflow run + every Mem0 run under a matrix root and
emits docs/benchmarks/findings/model-matrix-<date>.md answering: does a stronger answerer
help or hinder the summary (digest)? does block order matter, per model? Mem0 vs
stele head-to-head. Judge is held constant (gpt-4o), so differences are answerer
effects. Missing/partial runs are skipped, not fatal.
"""
from __future__ import annotations

import argparse
import glob
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SHORT = {
    "Intel/Qwen3-Coder-Next-int4-AutoRound": "qwen",
    "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit": "gemma",
}
# rough answerer-capability ordering (weak -> strong) for the narrative
_ORDER = ["qwen", "gemma", "gpt-4", "gpt-4o-mini", "gpt-4o", "gpt-5-mini", "gpt-5"]


def short(model: str) -> str:
    return _SHORT.get(model, model)


def _load(p: str) -> dict[str, Any] | None:
    try:
        return json.loads(Path(p).read_text())  # type: ignore[no-any-return]
    except Exception:
        return None


def collect(root: Path) -> tuple[dict, dict, dict]:
    # stele[(answerer, dataset, strategy)] = {"acc":.., "tok":..}
    stele: dict[tuple[str, str, str], dict[str, float]] = {}
    mem0: dict[tuple[str, str], dict[str, Any]] = {}
    versions: dict[str, str] = {}
    for p in glob.glob(str(root / "**" / "AnswerWorkflow.json"), recursive=True):
        d = _load(p)
        if not d or d.get("config", {}).get("judge_mode") != "openai":
            continue
        versions = d.get("versions", versions)
        ans = short(d["config"]["answer_model"])
        ds = d["config"]["scenarios_source"]
        for strat, row in d.get("by_strategy", {}).items():
            stele[(ans, ds, strat)] = {"acc": row["accuracy"], "tok": row["mean_total_tokens"]}
    for p in glob.glob(str(root / "mem0_*.json")):
        d = _load(p)
        if not d:
            continue
        mem0[(d.get("tag", "?"), d.get("benchmark", "locomo"))] = {
            "acc": d["accuracy"], "perf": d.get("perf", {}),
            "answer_model": short(d.get("answer_model", "?"))}
    return stele, mem0, versions


def _answerers(stele: dict) -> list[str]:
    seen = {a for (a, _, _) in stele}
    return [a for a in _ORDER if a in seen] + sorted(seen - set(_ORDER))


def render(root: Path) -> str:
    stele, mem0, versions = collect(root)
    answerers = _answerers(stele)
    datasets = sorted({ds for (_, ds, _) in stele})
    L: list[str] = [
        "# Model matrix — Mem0 vs stele across answerers (judge held constant)",
        "",
        f"Generated `{datetime.now(UTC).isoformat()}` · root `{root}`",
        "",
        "**Judge = gpt-4o for every row**, so differences are *answerer* effects, "
        "not judge effects. Packing: `search_first`=raw chunks, `digest`=lede "
        "summary+facts+top-5, `raw_fetch`=full context. Small N (LoCoMo 18, "
        "LongMemEval 12) — read as directional.",
        "",
        "**Versions**: " + ("  ·  ".join(f"{k} `{v}`" for k, v in versions.items()) or "n/a"),
        "",
    ]

    # 1. Headline: summary (digest) vs raw chunks (search_first) vs full, per answerer
    for ds in datasets:
        L += [f"## {ds}: does the summary help or hurt, per answerer?", "",
              "| answerer | search_first (raw) | digest (summary) | raw_fetch (full) | digest − search_first |",  # noqa: E501
              "| --- | ---: | ---: | ---: | ---: |"]
        for a in answerers:
            sf = stele.get((a, ds, "search_first"), {}).get("acc")
            dg = stele.get((a, ds, "digest"), {}).get("acc")
            rf = stele.get((a, ds, "raw_fetch"), {}).get("acc")
            delta = f"{dg - sf:+.3f}" if (dg is not None and sf is not None) else "-"
            f = lambda x: f"{x:.3f}" if x is not None else "-"  # noqa: E731
            L.append(f"| {a} | {f(sf)} | {f(dg)} | {f(rf)} | {delta} |")
        L.append("")

    # 2. Order permutations
    L += ["## Does block order matter? (digest variants)", "",
          "S=summary, F=facts, C=chunks. `digest`=SFC (default).", "",
          "| answerer | dataset | SFC | FCS | CSF | CFS |",
          "| --- | --- | ---: | ---: | ---: | ---: |"]
    f = lambda x: f"{x:.3f}" if x is not None else "-"  # noqa: E731
    for a in answerers:
        for ds in datasets:
            sfc = stele.get((a, ds, "digest"), {}).get("acc")
            fcs = stele.get((a, ds, "digest_fcs"), {}).get("acc")
            csf = stele.get((a, ds, "digest_csf"), {}).get("acc")
            cfs = stele.get((a, ds, "digest_cfs"), {}).get("acc")
            if any(v is not None for v in (fcs, csf, cfs)):
                L.append(f"| {a} | {ds} | {f(sfc)} | {f(fcs)} | {f(csf)} | {f(cfs)} |")
    L.append("")

    # 3. Mem0 vs stele (LoCoMo)
    L += ["## Mem0 vs stele (LoCoMo, same answerer + gpt-4o judge)", "",
          "| answerer | Mem0 | stele search_first | stele digest | stele raw_fetch | Mem0 mean_tok | Mem0 search_ms | Mem0 ingest_s |",  # noqa: E501
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    mem0_answerers = answerers + [a for (a, _ds) in mem0 if a not in answerers]
    for a in mem0_answerers:
        m = mem0.get((a, "locomo"))
        if not m:
            continue
        perf = m["perf"]
        sf = stele.get((a, "locomo", "search_first"), {}).get("acc")
        dg = stele.get((a, "locomo", "digest"), {}).get("acc")
        rf = stele.get((a, "locomo", "raw_fetch"), {}).get("acc")
        L.append(f"| {a} | {m['acc']:.3f} | {f(sf)} | {f(dg)} | {f(rf)} | "
                 f"{perf.get('mean_prompt_tokens','-')} | {perf.get('mean_search_ms','-')} | "
                 f"{perf.get('ingest_seconds_total','-')} |")
    L.append("")

    # 4. Full grid (every cell)
    L += ["## Full grid (accuracy @ mean tokens)", "",
          "| answerer | dataset | strategy | acc | tok |", "| --- | --- | --- | ---: | ---: |"]
    for (a, ds, strat) in sorted(stele):
        c = stele[(a, ds, strat)]
        L.append(f"| {a} | {ds} | {strat} | {c['acc']:.3f} | {c['tok']:.0f} |")
    L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    md = render(args.root)
    _date = datetime.now(UTC).strftime("%Y-%m-%d")
    out = args.out or Path(f"docs/benchmarks/findings/model-matrix-{_date}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    # also drop a copy + raw json index in the run root
    (args.root / "MODEL-MATRIX.md").write_text(md, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

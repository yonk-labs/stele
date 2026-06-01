# ruff: noqa: E501,SIM115  -- benchmark/diagnostic helper; brevity over ceremony.
"""Capture per-lane retrieved chunks for questions where raw_fetch beats digest.

Reads a chunker-shootout run, finds questions raw_fetch answered correctly but
digest did not, rebuilds each lane's index for those conversations, and writes
an eyeball-able tree:

    out/
      q01_<sid>/
        question.md           # question, gold, per-lane answer + correct flag
        raw_fetch.json        # {question, lane, answer, correct, chunks:[...]}
        digest.json
        consolidation.json
        enriching.json
      q02_.../ ...

So you can read exactly what each lane handed the model vs what raw_fetch had.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from pathlib import Path
from typing import Any

import lede

from benchmarks.external import loaders
from benchmarks.external.locomo_chunker_shootout import _cons_cfg, _dialog
from stele.core.config import (
    BackendConfig,
    IndexingConfig,
    RetrievalConfig,
    StashConfig,
)
from stele.core.stash import Stele


def _jscore(judge: Any, q: str, gold: str, ans: str) -> bool:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    rj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rj)
    return bool(rj._jscore_correct(judge, question=q, expected=gold, answer=ans))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shootout", default=None, help="shootout JSON (default: latest)")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/lane-gaps"))
    args = ap.parse_args()

    path = args.shootout or sorted(glob.glob("benchmarks/runs/chunker-shootout/shootout-*.json"))[-1]
    rows = json.load(open(path))["rows"]
    print(f"reading {path} ({len(rows)} rows)")

    from benchmarks.answer_workflow import OpenAICompatAnswerer
    key = os.environ["OPENAI_API_KEY"]
    judge = OpenAICompatAnswerer(answer_model="gpt-4o", judge_model="gpt-4o",
                                 base_url="https://api.openai.com/v1", api_key=key)

    # group rows by (sid, question) -> {tag: row}
    byq: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        byq.setdefault((r["sid"], r["question"]), {})[r["tag"]] = r

    # pick questions where raw_fetch is correct and digest is not
    picks: list[tuple[str, str, dict[str, Any]]] = []
    for (sid, q), lanes in byq.items():
        if "raw_fetch" not in lanes or "digest" not in lanes:
            continue
        gold = lanes["raw_fetch"]["expected"]
        raw_ok = _jscore(judge, q, gold, lanes["raw_fetch"]["answer"])
        dig_ok = _jscore(judge, q, gold, lanes["digest"]["answer"])
        if raw_ok and not dig_ok:
            picks.append((sid, q, lanes))
        if len(picks) >= args.n:
            break
    print(f"selected {len(picks)} raw-wins / digest-loses questions")

    # rebuild indexes per needed conversation, capture chunks
    samples = {s["sample_id"]: s for s in loaders.load_locomo()}
    args.out.mkdir(parents=True, exist_ok=True)
    for i, (sid, q, lanes) in enumerate(picks, 1):
        s = samples[sid]
        text = _dialog(s["conversation"])
        fo = Stele(config=StashConfig(
            backend=BackendConfig(type="sqlite", path=f"/tmp/gap-fo-{sid}.db"),
            indexing=IndexingConfig(mode="sync", provider="chunkshop"),
            retrieval=RetrievalConfig(default_mode="hybrid")))
        co = Stele(config=_cons_cfg(f"/tmp/gap-co-{sid}.db",
                   "benchmarks.external.consolidators.extractive", 200, 60))
        en = Stele(config=_cons_cfg(f"/tmp/gap-en-{sid}.db",
                   "benchmarks.external.consolidators.enriching", 1000, 1000))
        fo_ref = fo.store(text, namespace=sid).reference
        co.store(text, namespace=sid)
        en.store(text, namespace=sid)

        dh = fo.search(fo_ref, q, limit=10, mode="hybrid")
        digest_chunks = [h.text for h in dh]
        report = lede.readable_report("\n\n".join(digest_chunks), hints=[q]).to_markdown() if dh else ""
        lane_chunks = {
            "raw_fetch": [text],  # the whole conversation
            "digest": [report] + [f"[chunk] {c}" for c in digest_chunks[:5]],
            "consolidation": [h.text for h in co.query(sid, q, limit=15, mode="hybrid")],
            "enriching": [h.text for h in en.query(sid, q, limit=15, mode="hybrid")],
        }
        for st in (fo, co, en):
            st.close()

        gold = lanes["raw_fetch"]["expected"]
        slug = re.sub(r"[^a-z0-9]+", "-", q.lower())[:40].strip("-")
        d = args.out / f"q{i:02d}_{sid}_{slug}"
        d.mkdir(parents=True, exist_ok=True)
        md = [f"# {q}", "", f"- **sid:** {sid}", f"- **gold:** {gold}", "",
              "| lane | correct | answer |", "|---|---|---|"]
        for tag in ("raw_fetch", "digest", "consolidation", "enriching"):
            row = lanes.get(tag, {})
            ans = (row.get("answer", "") or "").replace("\n", " ")[:160]
            ok = _jscore(judge, q, gold, row["answer"]) if row else False
            md.append(f"| {tag} | {'✓' if ok else '✗'} | {ans} |")
        (d / "question.md").write_text("\n".join(md))
        for tag, chunks in lane_chunks.items():
            row = lanes.get(tag, {})
            (d / f"{tag}.json").write_text(json.dumps({
                "question": q, "sid": sid, "gold": gold, "lane": tag,
                "answer": row.get("answer", ""),
                "n_chunks": len(chunks), "chunks": chunks,
            }, indent=2))
        print(f"  wrote {d}")
    print(f"\ndone -> {args.out}")


if __name__ == "__main__":
    main()

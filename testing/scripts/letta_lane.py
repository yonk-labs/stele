# ruff: noqa: E501,E702,SIM105  -- standalone; runs under SYSTEM python3 (letta_client), NOT stele's .venv.
"""Letta competitor lane — archival memory, same corpora/answerer/judge as the others.

Letta runs as a server (docker letta/letta on :8283, bundled pg+pgvector). For each
unit we create an agent, chunk the content into archival passages, then per question
search Letta's archival memory and feed the retrieved passages to the SAME qwen@193
answerer + verbatim gemma@133 jscore judge. Path-A (memory-as-retrieval-substrate),
matching how the Mem0 lane was run.

Caveat: Letta's archival embedder is openai/text-embedding-3-small (its native config),
not bge — note that when comparing to stele/mem0 (which use bge).

Run:  python3 -m benchmarks.external.letta_lane --per-corpus 40        # SYSTEM python3
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from letta_client import Letta

from benchmarks.external.mem0_lane import _answer, _jscore

_LETTA = Letta(base_url="http://localhost:8283")
_MODEL = "openai/gpt-5-mini"          # agent LLM (unused in path A)
_EMBED = "openai/text-embedding-3-small"  # archival embedder (Letta-native)


def _chunks(text: str, size: int = 1500) -> list[str]:
    out, buf = [], []
    n = 0
    for para in text.split("\n"):
        if n + len(para) > size and buf:
            out.append("\n".join(buf)); buf, n = [], 0
        buf.append(para); n += len(para) + 1
    if buf:
        out.append("\n".join(buf))
    return [c for c in out if c.strip()]


def _run_unit(content: str, qas: list[dict]) -> list[dict]:
    agent = _LETTA.agents.create(
        name=f"bench-{int(time.time()*1000) % 10_000_000}",
        model=_MODEL, embedding=_EMBED,
        memory_blocks=[{"label": "human", "value": "benchmark"},
                       {"label": "persona", "value": "archival store"}],
    )
    rows = []
    try:
        for ch in _chunks(content):
            try:
                _LETTA.agents.passages.create(agent_id=agent.id, text=ch)
            except Exception:
                pass
        for qa in qas:
            q, gold = qa["q"], qa["gold"]
            mems, ctx_chars, retr_ms, ans_ms = [], 0, 0.0, 0.0
            try:
                _s = time.perf_counter()
                res = _LETTA.agents.passages.search(agent_id=agent.id, query=q)
                retr_ms = (time.perf_counter() - _s) * 1000
                items = res if isinstance(res, list) else getattr(res, "results", [])
                mems = [getattr(it, "content", getattr(it, "text", "")) for it in items][:10]
                ctx = "\n".join(mems); ctx_chars = len(ctx)
                _s = time.perf_counter()
                a = _answer(ctx, q)
                ans_ms = (time.perf_counter() - _s) * 1000
                correct = _jscore(q, gold, a)
            except Exception as e:
                correct = False
                a = f"(error: {str(e)[:80]})"
            rows.append({"q": q, "gold": gold, "answer": a, "correct": correct, "n_mems": len(mems),
                         "ctx_chars": ctx_chars, "retr_ms": round(retr_ms, 1), "ans_ms": round(ans_ms, 1)})
    finally:
        try:
            _LETTA.agents.delete(agent.id)
        except Exception:
            pass
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", type=Path, default=Path("benchmarks/runs/cross-corpus/units.json"))
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--corpora", nargs="+", default=None)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cross-corpus"))
    args = ap.parse_args()
    units = json.loads(args.units.read_text())
    if args.corpora:
        units = {k: v for k, v in units.items() if k in args.corpora}

    tally, rows = {}, []
    for corpus, unit_list in units.items():
        ok = n = 0
        done = 0
        for u in unit_list:
            if done >= args.per_corpus:
                break
            urows = _run_unit(u["content"], u["qas"])
            for r in urows:
                r["corpus"] = corpus; r["unit"] = u["unit_id"]
                ok += r["correct"]; n += 1; done += 1
                rows.append(r)
            print(f"  {corpus}: {done} done ({ok}/{n} ok)", flush=True)
        tally[corpus] = {"ok": ok, "n": n}
        print(f"[letta:{corpus}] {ok}/{n}", flush=True)

    print("\n=== LETTA LANE TALLY ===")
    for corpus, t in tally.items():
        acc = t["ok"] / t["n"] if t["n"] else 0.0
        print(f"  {corpus:20s} {t['ok']:>3d}/{t['n']:<3d} ({acc:.2f})")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"letta-lane-{stamp}.json"
    f.write_text(json.dumps({"system": "letta", "embedder": _EMBED, "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

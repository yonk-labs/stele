# ruff: noqa: E501,E702  -- standalone; runs under SYSTEM python3 (mem0 stack), NOT stele's .venv.
"""Fair Mem0 LoCoMo lane — PER-SESSION ingestion (how Mem0 is designed to be used).

The first Mem0 lane fed each whole 60k-char transcript as one add(), which starved
Mem0's memory graph (only ~2.5 memories/question -> 0.04). Mem0's LoCoMo protocol
adds conversation turns incrementally. This reads locomo_turns.json (sessions of
role-tagged messages) and add()s each session in order, then answers/judges with
the SAME qwen@193 answerer + verbatim gemma@133 jscore as every other lane.

Run:  python3 -m benchmarks.external.mem0_locomo_turns        # SYSTEM python3
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from benchmarks.external.mem0_lane import _answer, _jscore, _make_memory


def main() -> None:
    import os
    turns_file = os.environ.get("MEM0_TURNS_FILE", "benchmarks/runs/cross-corpus/locomo_turns.json")
    turns = json.loads(Path(turns_file).read_text())
    ok = n = 0
    rows = []
    for ci, conv in enumerate(turns):
        mem = _make_memory()
        mem.reset()
        added = 0
        for session in conv["sessions"]:
            try:
                mem.add(session, user_id="u")
                added += 1
            except Exception as e:
                rows.append({"unit": conv["unit_id"], "session_add_error": str(e)[:160]})
        for qa in conv["qas"]:
            q, gold = qa["q"], qa["gold"]
            mems, ctx_chars, retr_ms, ans_ms = [], 0, 0.0, 0.0
            try:
                _s = time.perf_counter()
                res = mem.search(q, filters={"user_id": "u"}, top_k=10)
                retr_ms = (time.perf_counter() - _s) * 1000
                mems = [m.get("memory", "") for m in (res.get("results") or [])]
                ctx = "\n".join(mems); ctx_chars = len(ctx)
                _s = time.perf_counter()
                a = _answer(ctx, q)
                ans_ms = (time.perf_counter() - _s) * 1000
                correct = _jscore(q, gold, a)
            except Exception as e:
                correct = False
                a = f"(error: {str(e)[:80]})"
            ok += correct
            n += 1
            rows.append({"unit": conv["unit_id"], "q": q, "gold": gold, "answer": a,
                         "correct": correct, "n_mems": len(mems),
                         "ctx_chars": ctx_chars, "retr_ms": round(retr_ms, 1), "ans_ms": round(ans_ms, 1)})
        print(f"  conv {ci+1}/{len(turns)} ({conv['unit_id']}): {added} sessions added, "
              f"running {ok}/{n}", flush=True)

    acc = ok / n if n else 0.0
    print(f"\n=== MEM0 LoCoMo (per-session ingestion) ===\n  {ok}/{n}  ({acc:.2f})")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = Path(f"benchmarks/runs/cross-corpus/mem0-locomo-turns-{stamp}.json")
    f.write_text(json.dumps({"system": "mem0-per-session", "ok": ok, "n": n, "acc": acc, "rows": rows}, indent=2))
    print(f"wrote {f}")


if __name__ == "__main__":
    main()

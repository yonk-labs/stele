# ruff: noqa: E501,SIM115,E702  -- benchmark control.
"""NO-CONTEXT parametric floor: answer every question with EMPTY memory.

Quantifies how much of each corpus the answerer (qwen@193) gets right from
PRETRAINING alone — the floor that retrieval scores must be measured against.
LoCoMo (private conversations) should floor near 0; factoid corpora (hotpotqa/
covidqa about famous entities) may floor much higher, inflating every system's
factoid number. Subtract this floor to get the real retrieval contribution.

Run: OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.no_context_baseline
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_shootout import _answer

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", type=Path, default=Path("benchmarks/runs/cross-corpus/high_n_units.json"))
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cross-corpus"))
    args = ap.parse_args()
    units = json.loads(args.units.read_text())

    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec); spec.loader.exec_module(rj)
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_GEMMA,
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="http://192.168.1.133:8000/v1", judge_api_key="local")
    judge = OpenAICompatAnswerer(answer_model=_GEMMA, judge_model=_GEMMA,
                                 base_url="http://192.168.1.133:8000/v1", api_key="local")

    tally, rows = {}, []
    for corpus, unit_list in units.items():
        ok = n = 0
        for u in unit_list:
            for qa in u["qas"]:
                q, gold = qa["q"], qa["gold"]
                a = _answer(ans, "(no memory available)", q)  # EMPTY context
                correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                ok += correct; n += 1
                rows.append({"corpus": corpus, "q": q, "gold": gold, "answer": a, "correct": correct})
                if n % 25 == 0:
                    print(f"  {corpus}: {n} done ({ok}/{n})", flush=True)
        tally[corpus] = {"ok": ok, "n": n}
        print(f"[no-context:{corpus}] {ok}/{n} = {ok/n if n else 0:.2f}", flush=True)

    print("\n=== NO-CONTEXT PARAMETRIC FLOOR ===")
    for corpus, t in tally.items():
        print(f"  {corpus:20s} {t['ok']:>3d}/{t['n']:<3d} ({t['ok']/t['n'] if t['n'] else 0:.3f})")
    import time
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (args.out / f"no-context-floor-{stamp}.json").write_text(json.dumps({"tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote no-context-floor-{stamp}.json")


if __name__ == "__main__":
    main()

"""Re-judge answer-workflow results with a different judge model.

Each result row now carries (question, expected, answer, context), so we can
replay JUST the judge step with another model — isolating the judge's effect on
identical answers. Used to have gpt-5.5 judge the answers gpt-4o originally
judged. Writes <root>/REJUDGE-<judge>.json + prints per-(answerer,strategy)
accuracy under both judges.
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer

_SHORT = {
    "Intel/Qwen3-Coder-Next-int4-AutoRound": "qwen",
    "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit": "gemma",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--judge-model", default="gpt-5.5")
    ap.add_argument("--judge-base-url", default="https://api.openai.com/v1")
    ap.add_argument("--strategies", default="")  # empty = all
    args = ap.parse_args()
    import os

    key = os.environ["OPENAI_API_KEY"]
    judge = OpenAICompatAnswerer(
        answer_model=args.judge_model, judge_model=args.judge_model,
        base_url=args.judge_base_url, api_key=key,
    )
    only = {s for s in args.strategies.split(",") if s}
    # (answerer, strategy) -> [n, new_correct, orig_correct]
    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    rows_out: list[dict[str, Any]] = []
    for awj in glob.glob(str(args.root / "**" / "AnswerWorkflow.json"), recursive=True):
        cfg = json.loads(Path(awj).read_text()).get("config", {})
        answerer = _SHORT.get(cfg.get("answer_model", "?"), cfg.get("answer_model", "?"))
        rpath = Path(awj).with_name("results.jsonl")
        if not rpath.exists():
            continue
        for line in rpath.read_text().splitlines():
            r = json.loads(line)
            strat = r["strategy"]
            if only and strat not in only:
                continue
            if not r.get("context"):
                continue
            try:
                v = judge.judge(question=r["question"], expected_answer=r["expected"],
                                answer=r["answer"], context=r["context"])
                newc = bool(v.correct)
            except Exception as e:
                newc = False
                r["rejudge_error"] = str(e)[:100]
            a = agg[(answerer, strat)]
            a[0] += 1
            a[1] += int(newc)
            a[2] += int(r["correct"])
            rows_out.append({
                "answerer": answerer, "strategy": strat, "q": r["question"][:80],
                "orig_correct": r["correct"], "new_correct": newc,
            })
    summary = {
        f"{ans}|{st}": {
            "n": v[0],
            f"{args.judge_model}_acc": round(v[1] / v[0], 4),
            "gpt-4o_acc": round(v[2] / v[0], 4),
        }
        for (ans, st), v in sorted(agg.items()) if v[0]
    }
    out = args.root / f"REJUDGE-{args.judge_model}.json"
    payload = {"judge": args.judge_model, "summary": summary, "rows": rows_out}
    out.write_text(json.dumps(payload, indent=2))
    print(f"wrote {out}")
    jm = args.judge_model
    for k, v in summary.items():
        print(f"  {k:28s} n={v['n']:3d}  {jm}={v[f'{jm}_acc']:.3f}  gpt-4o={v['gpt-4o_acc']:.3f}")


if __name__ == "__main__":
    main()

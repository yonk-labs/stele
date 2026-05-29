"""Re-judge answer-workflow results with a different judge model.

Each result row now carries (question, expected, answer, context), so we can
replay JUST the judge step with another model — isolating the judge's effect on
identical answers. Used to have gpt-5.5 judge the answers gpt-4o originally
judged. Writes <root>/REJUDGE-<judge>.json + prints per-(answerer,strategy)
accuracy under both judges.
"""
# ruff: noqa: E501  -- the jscore prompt is verbatim from Mem0; keep lines byte-faithful.
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

_STRICT_BENCH_SYSTEM = (
    "You are a benchmark scorer. Score the candidate answer against the "
    "benchmark's gold answer. Two independent judgments:\n\n"
    "1) match — Mark TRUE only if the candidate explicitly contains the "
    "gold answer (a clear paraphrase or alias is OK). Mark FALSE if the "
    "candidate is missing the gold, contradicts it, gives a different fact, "
    "refuses ('I do not have enough information'), or hedges past commitment. "
    "Do NOT use your own knowledge to decide whether the gold answer is "
    "'really' correct in the world. The gold IS the answer for this benchmark.\n\n"
    "2) context_sufficient — INDEPENDENT of `match`. Mark TRUE only if a "
    "careful reader could derive the gold answer from the provided context "
    "alone, with no outside knowledge. If context is empty, mark FALSE.\n\n"
    "Return JSON only with keys: match (bool), context_sufficient (bool), "
    "confidence (0..1 on `match`), rationale (one short sentence)."
)


# Mem0's published LoCoMo "J-score" judge (verbatim, no-evidence variant).
# Source: github.com/mem0ai/memory-benchmarks benchmarks/locomo/prompts.py.
# Lenient by design (partial credit, paraphrase, +/-14-day dates) and judges
# generated-vs-gold ONLY (no retrieval context). Lets us score on the same
# ruler Mem0/the field report.
_JSCORE_SYSTEM = ("You are evaluating conversational AI memory recall. "
                  "Return JSON only with the format requested.")
_JSCORE_TEMPLATE = """Label the generated answer as CORRECT or WRONG.

## Rules

1. **PARTIAL CREDIT**: If the generated answer includes AT LEAST ONE correct item from the gold answer's list, mark CORRECT. Getting 1 out of 2, 2 out of 4, etc. is always acceptable. Only mark WRONG if NONE of the gold answer items appear.

2. **PARAPHRASES COUNT**: Same concept in different words is CORRECT. Judge semantic meaning, not exact wording. Emotions/sentiments in the same positive/negative family count as paraphrases.

3. **EXTRA DETAIL IS FINE**: A longer answer that includes the gold answer's key facts plus additional information is CORRECT. Never penalize for being more detailed or specific.

4. **DATE TOLERANCE**: Dates within 14 days of each other are CORRECT. Durations within 50% are CORRECT. Relative dates match specific dates in the same window. Converting "last year" to the actual year is CORRECT.

5. **SEMANTIC OVERLAP**: Judge whether the generated answer addresses the same topic and captures the core idea of the gold answer. Different wording/phrasing/detail should not result in WRONG if the underlying concept matches.

6. **SAME REFERENT**: If the generated answer references the same named entity/person/concept as the gold answer, mark CORRECT even with a different description or extra details.

7. **FOCUS ON KNOWLEDGE, NOT WORDING**: Assess whether the system recalled the right fact. Only mark WRONG when the answer demonstrates a genuinely different or incorrect understanding.

## ONLY mark WRONG if:
- The generated answer contains ZERO correct items from the gold answer
- The answer addresses a completely different topic

## Question
Question: {question}
Gold answer: {answer}
Generated answer: {response}

Return JSON with "reasoning" (one sentence) and "label" (CORRECT or WRONG). Do NOT include both labels."""


def _jscore_correct(judge: OpenAICompatAnswerer, *, question: str, expected: str,
                    answer: str) -> bool:
    """Mem0 J-score judge: generated-vs-gold only (no context). label==CORRECT."""
    user = _JSCORE_TEMPLATE.format(question=question, answer=expected or "(none)", response=answer)
    content = judge._chat(  # noqa: SLF001
        model=judge.judge_model, json_mode=True,
        messages=[{"role": "system", "content": _JSCORE_SYSTEM},
                  {"role": "user", "content": user}],
    )
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```")[1].removeprefix("json").strip()
    return str(json.loads(s).get("label", "")).upper() == "CORRECT"


def _strict_correct(judge: OpenAICompatAnswerer, *, question: str, expected: str,
                    answer: str, context: str) -> bool:
    """Strict-bench judge: abstention/refusal => FALSE. Returns the `match` bool."""
    user_msg = (
        f"Question:\n{question}\n\nGold answer:\n{expected or '(none)'}\n\n"
        f"Candidate answer:\n{answer}\n\nContext the candidate had:\n{context or '(none)'}"
    )
    content = judge._chat(  # noqa: SLF001 — intentional plumbing reuse
        model=judge.judge_model, json_mode=True,
        messages=[{"role": "system", "content": _STRICT_BENCH_SYSTEM},
                  {"role": "user", "content": user_msg}],
    )
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```")[1].removeprefix("json").strip()
    return bool(json.loads(s).get("match", False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--judge-model", default="gpt-5.5")
    ap.add_argument("--judge-base-url", default="https://api.openai.com/v1")
    ap.add_argument("--strategies", default="")  # empty = all
    ap.add_argument("--prompt", default="default",
                    choices=["default", "strict-bench", "jscore"])
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
                if args.prompt == "jscore":
                    newc = _jscore_correct(judge, question=r["question"],
                                           expected=r["expected"], answer=r["answer"])
                elif args.prompt == "strict-bench":
                    newc = _strict_correct(judge, question=r["question"], expected=r["expected"],
                                           answer=r["answer"], context=r["context"])
                else:
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
            "rejudged_acc": round(v[1] / v[0], 4),
            "orig_acc": round(v[2] / v[0], 4),
        }
        for (ans, st), v in sorted(agg.items()) if v[0]
    }
    out = args.root / f"REJUDGE-{args.judge_model}-{args.prompt}.json"
    payload = {"judge": args.judge_model, "prompt": args.prompt,
               "summary": summary, "rows": rows_out}
    out.write_text(json.dumps(payload, indent=2))
    print(f"wrote {out}")
    for k, v in summary.items():
        print(f"  {k:28s} n={v['n']:3d}  rejudged({args.judge_model}/{args.prompt})="
              f"{v['rejudged_acc']:.3f}  orig={v['orig_acc']:.3f}")


if __name__ == "__main__":
    main()

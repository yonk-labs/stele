# ruff: noqa: E501,SIM115  -- diagnostic helper.
"""Fast eval over the stored lane-gap folders — answer from STORED chunks.

No retrieval, no indexing: read each question folder's per-lane chunk JSONs,
re-answer from those exact chunks (qwen), jscore, and write a timestamped
results-<ts>.json into the same folder so old/new runs can be diffed.

Adds the ADDITIVE enriching model you described: keep a lane's existing chunks
(the text stays) and APPEND a small block of resolved facts ("[Speaker] ...
[date: 2022]"). Tested as `digest_plus_facts` = digest chunks + enriching facts.
This isolates "does adding resolved facts to digest's context help" from the
broken replace-the-substrate experiment.

Run: python -m benchmarks.external.lane_gap_eval
"""
from __future__ import annotations

import glob
import json
import os
import time
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_ROOT = Path("benchmarks/runs/lane-gaps")


def _answer(ans: OpenAICompatAnswerer, ctx: str, q: str) -> str:
    user = (
        "Answer using ONLY the memory record. If absent, say "
        "\"I do not have enough information to answer.\"\n\n"
        f"[MEMORY]\n{ctx}\n\n[QUESTION] {q}"
    )
    return str(ans._chat(model=_QWEN, json_mode=False,
                         messages=[{"role": "user", "content": user}])).strip()


def main() -> None:
    key = os.environ["OPENAI_API_KEY"]
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model="gpt-4o",
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="https://api.openai.com/v1", judge_api_key=key)
    import importlib.util
    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rj)
    judge = OpenAICompatAnswerer(answer_model="gpt-4o", judge_model="gpt-4o",
                                 base_url="https://api.openai.com/v1", api_key=key)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    agg: dict[str, list[int]] = {}
    for folder in sorted(glob.glob(str(_ROOT / "q*"))):
        d = Path(folder)
        lanes: dict[str, dict[str, Any]] = {}
        for lj in d.glob("*.json"):
            if lj.name.startswith("results-"):
                continue
            lanes[lj.stem] = json.loads(lj.read_text())
        if "digest" not in lanes:
            continue
        q = lanes["digest"]["question"]
        gold = lanes["digest"]["gold"]

        # contexts from STORED chunks (text stays as captured)
        ctxs: dict[str, str] = {}
        for tag, data in lanes.items():
            ctxs[tag] = "\n\n".join(data.get("chunks", []))
        # ADDITIVE: digest chunks + appended resolved facts (the enriching spans)
        if "enriching" in lanes:
            facts = "\n".join(f"- {c}" for c in lanes["enriching"].get("chunks", []))
            ctxs["digest_plus_facts"] = ctxs["digest"] + "\n\n[RESOLVED FACTS]\n" + facts

        out: dict[str, Any] = {"question": q, "gold": gold, "lanes": {}}
        for tag, ctx in ctxs.items():
            a = _answer(ans, ctx, q)
            ok = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
            out["lanes"][tag] = {"answer": a, "correct": ok, "ctx_chars": len(ctx)}
            agg.setdefault(tag, []).append(int(ok))
        (d / f"results-{stamp}.json").write_text(json.dumps(out, indent=2))
        print(f"{d.name}: " + "  ".join(
            f"{t}={'✓' if out['lanes'][t]['correct'] else '✗'}" for t in out["lanes"]))

    n_agg = len(next(iter(agg.values()))) if agg else 0
    print(f"\n=== aggregate (n={n_agg} questions) ===")
    for tag, oks in sorted(agg.items(), key=lambda kv: -sum(kv[1])):
        print(f"  {tag:18} {sum(oks)}/{len(oks)} correct")


if __name__ == "__main__":
    main()

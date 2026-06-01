# ruff: noqa: E501,E702  -- standalone; runs under SYSTEM python3 (mem0 venv), NOT stele's .venv.
"""Mem0 competitor lane — same corpora/answerer/judge as the stele cross-corpus run.

Reads benchmarks/runs/cross-corpus/units.json (dumped from stele's loaders so the
inputs are byte-identical), runs each unit through Mem0's own extract->store->
retrieve, then feeds Mem0's retrieved memories to the SAME answerer (qwen@193) and
the SAME verbatim Mem0 jscore judge (gemma@133). This isolates the memory system.

Mem0 config: llm=openai->qwen@193, embedder=fastembed bge-base (matches stele),
vector_store=faiss (local, server-less). Fresh memory per unit (reset between).

Run:  python3 -m benchmarks.external.mem0_lane --per-corpus 75      # SYSTEM python3
  (or)  python3 benchmarks/external/mem0_lane.py
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import openai as _openai_pkg
from mem0 import Memory
from openai import OpenAI

_MEM_COUNTER = itertools.count()


def _patch_openai_for_gpt5() -> None:
    """gpt-5 family rejects max_tokens (needs max_completion_tokens) and any
    temperature != 1. mem0 sends both, so every gpt-5 extraction 400s. Translate
    at the client layer — only for gpt-5 models, so local qwen/gemma are untouched."""
    comp = _openai_pkg.resources.chat.completions.Completions
    if getattr(comp, "_gpt5_patched", False):
        return
    orig = comp.create

    def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(kwargs.get("model", "")).startswith("gpt-5"):
            if "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
            if kwargs.get("temperature") not in (None, 1, 1.0):
                kwargs.pop("temperature", None)
            # gpt-5 reasoning models reject sampling params entirely.
            for p in ("top_p", "frequency_penalty", "presence_penalty"):
                kwargs.pop(p, None)
            # Turn reasoning OFF: reasoning tokens otherwise derail mem0's
            # structured-JSON extraction (the 0/70 LoCoMo artifact).
            kwargs.setdefault("reasoning_effort", "minimal")
        return orig(self, *args, **kwargs)

    comp.create = create
    comp._gpt5_patched = True


_patch_openai_for_gpt5()

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_ANS = OpenAI(base_url="http://192.168.1.193:8000/v1", api_key="local")
_JUDGE = OpenAI(base_url="http://192.168.1.133:8000/v1", api_key="local")

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


def _answer(ctx: str, q: str) -> str:
    user = ("Answer using ONLY the memory record. If absent, say "
            "\"I do not have enough information to answer.\"\n\n"
            f"[MEMORY]\n{ctx}\n\n[QUESTION] {q}")
    r = _ANS.chat.completions.create(model=_QWEN, messages=[{"role": "user", "content": user}])
    return (r.choices[0].message.content or "").strip()


def _jscore(question: str, gold: str, answer: str) -> bool:
    user = _JSCORE_TEMPLATE.format(question=question, answer=gold or "(none)", response=answer)
    r = _JUDGE.chat.completions.create(
        model=_GEMMA, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _JSCORE_SYSTEM}, {"role": "user", "content": user}])
    s = (r.choices[0].message.content or "").strip()
    if s.startswith("```"):
        s = s.split("```")[1].removeprefix("json").strip()
    try:
        return str(json.loads(s).get("label", "")).upper() == "CORRECT"
    except Exception:
        return False


def _make_memory() -> Memory:
    # Extractor LLM is env-configurable so we can swap qwen-local -> gpt-5-mini
    # (the "extractor strength" axis). Embedder/answerer/judge stay fixed.
    import os
    model = os.environ.get("MEM0_LLM_MODEL", _QWEN)
    base = os.environ.get("MEM0_LLM_BASE_URL", "http://192.168.1.193:8000/v1")
    key = os.environ.get("MEM0_LLM_API_KEY", "local")
    llm_cfg: dict = {"model": model, "api_key": key, "temperature": 0.0}
    if base:  # empty -> mem0 uses the default OpenAI endpoint (api.openai.com)
        llm_cfg["openai_base_url"] = base
    # Fresh faiss collection per Memory (unique path) so units never share state.
    uid = next(_MEM_COUNTER)
    base_path = os.environ.get("MEM0_FAISS_PATH", "/tmp/mem0_faiss")
    config = {
        "llm": {"provider": "openai", "config": llm_cfg},
        "embedder": {"provider": "fastembed", "config": {"model": "BAAI/bge-base-en-v1.5"}},
        "vector_store": {"provider": "faiss", "config": {
            "collection_name": os.environ.get("MEM0_FAISS_COLLECTION", "mem0lane") + f"_{uid}",
            "embedding_model_dims": 768,
            "path": f"{base_path}_{uid}"}},
    }
    return Memory.from_config(config)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", type=Path, default=Path("benchmarks/runs/cross-corpus/units.json"))
    ap.add_argument("--per-corpus", type=int, default=75)
    ap.add_argument("--corpora", nargs="+", default=None, help="subset of corpora to run")
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cross-corpus"))
    args = ap.parse_args()
    units = json.loads(args.units.read_text())
    if args.corpora:
        units = {k: v for k, v in units.items() if k in args.corpora}

    tally: dict[str, dict[str, int]] = {}
    rows = []
    for corpus, unit_list in units.items():
        ok = n = failed = 0
        done = 0
        for u in unit_list:
            content, qas = u["content"], u["qas"]
            if done >= args.per_corpus:
                break
            try:
                mem = _make_memory()
                mem.reset()
                mem.add(content, user_id="u")
            except Exception as e:  # mem0 add can choke on huge transcripts
                failed += len(qas)
                n += len(qas)
                done += len(qas)
                rows.append({"corpus": corpus, "unit": u["unit_id"], "add_error": str(e)[:200]})
                continue
            for qa in qas:
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
                done += 1
                rows.append({"corpus": corpus, "unit": u["unit_id"], "q": q, "gold": gold,
                             "answer": a, "correct": correct, "n_mems": len(mems),
                             "ctx_chars": ctx_chars, "retr_ms": round(retr_ms, 1), "ans_ms": round(ans_ms, 1)})
                if done % 10 == 0:
                    print(f"  {corpus}: {done} done ({ok}/{n} ok, {failed} add-fail)", flush=True)
        tally[corpus] = {"ok": ok, "n": n, "add_failed": failed}
        print(f"[mem0:{corpus}] {ok}/{n}  (add-failures={failed})", flush=True)

    print("\n=== MEM0 LANE TALLY ===")
    for corpus, t in tally.items():
        acc = t["ok"] / t["n"] if t["n"] else 0.0
        print(f"  {corpus:20s} {t['ok']:>3d}/{t['n']:<3d} ({acc:.2f})  add-fail={t['add_failed']}")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"mem0-lane-{stamp}.json"
    f.write_text(json.dumps({"system": "mem0", "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

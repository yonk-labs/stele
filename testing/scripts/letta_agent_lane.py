# ruff: noqa: E501,E702,SIM105  -- standalone; SYSTEM python3 (letta_client), NOT stele's .venv.
"""Letta AGENT-MODE lane — the full agent loop (Letta-as-a-system, not just archival).

Per unit: create an agent, load the content into archival memory, then ask each
question via the agent loop (agents.messages.create). Letta itself decides to
search its archival memory, reasons, and answers. Judged by the same gemma@133
jscore. Unlike the archival lane, the ANSWER comes from Letta's own LLM
(openai/gpt-4.1-mini here — no local-qwen handle), so this is "Letta end-to-end,
GPT-answered", a different (more faithful) comparison than the common-answerer lanes.

Run:  python3 -m benchmarks.external.letta_agent_lane --per-corpus 40
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from letta_client import Letta

from benchmarks.external.letta_lane import _chunks
from benchmarks.external.mem0_lane import _jscore

_LETTA = Letta(base_url="http://localhost:8283")
_MODEL = "openai/gpt-5-mini"
_EMBED = "openai/text-embedding-3-small"
_PERSONA = ("You answer the user's question using ONLY your archival memory. "
            "ALWAYS call archival_memory_search first to find relevant facts, then "
            "answer concisely. If nothing relevant is found, say you don't have enough information.")


def _agent_answer(agent_id: str, q: str) -> str:
    resp = _LETTA.agents.messages.create(
        agent_id=agent_id,
        messages=[{"role": "user", "content": f"{q}\nAnswer concisely using your archival memory."}])
    msgs = resp.messages if hasattr(resp, "messages") else resp
    out = [getattr(m, "content", "") for m in msgs
           if getattr(m, "message_type", "") == "assistant_message"]
    return (out[-1] if out else "").strip()


def _run_unit(content: str, qas: list[dict]) -> list[dict]:
    agent = _LETTA.agents.create(
        name=f"am-{int(time.time()*1000) % 10_000_000}", model=_MODEL, embedding=_EMBED,
        memory_blocks=[{"label": "human", "value": "benchmark"}, {"label": "persona", "value": _PERSONA}])
    rows = []
    try:
        for ch in _chunks(content):
            try:
                _LETTA.agents.passages.create(agent_id=agent.id, text=ch)
            except Exception:
                pass
        time.sleep(1)  # let archival embeddings settle before querying
        for qa in qas:
            q, gold = qa["q"], qa["gold"]
            try:
                a = _agent_answer(agent.id, q)
                correct = _jscore(q, gold, a)
            except Exception as e:
                a, correct = f"(error: {str(e)[:80]})", False
            rows.append({"q": q, "gold": gold, "answer": a, "correct": correct})
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
        ok = n = done = 0
        for u in unit_list:
            if done >= args.per_corpus:
                break
            for r in _run_unit(u["content"], u["qas"]):
                r["corpus"], r["unit"] = corpus, u["unit_id"]
                ok += r["correct"]; n += 1; done += 1
                rows.append(r)
            print(f"  {corpus}: {done} done ({ok}/{n} ok)", flush=True)
        tally[corpus] = {"ok": ok, "n": n}
        print(f"[letta-agent:{corpus}] {ok}/{n}", flush=True)

    print("\n=== LETTA AGENT-MODE TALLY ===")
    for corpus, t in tally.items():
        print(f"  {corpus:20s} {t['ok']:>3d}/{t['n']:<3d} ({t['ok']/t['n'] if t['n'] else 0:.2f})")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"letta-agent-{stamp}.json"
    f.write_text(json.dumps({"system": "letta-agent", "model": _MODEL, "tally": tally, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()

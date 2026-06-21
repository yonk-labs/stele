"""Real-LLM lane for the evolving-world benchmark (thin, network-gated).

Catches the staleness class the deterministic core cannot see: when a REAL
extraction model drifts on subject_label / aspect across sessions, even a
STABLE-subject evolving fact can land in two slots and leave a stale sibling
active (issue #72's `replicas` finding). For each evolving fact we ingest a
sequence of natural-language artifacts through `from_session` twice:

- `ideal`     — a deterministic stub that always emits the stable canonical
  subject + aspect. Perfect extraction; supersession always fires; 0 staleness.
- `real-llm`  — a real model reads the noisy artifact and extracts freely.

The gap between them is extraction-induced staleness. Together with the main
deterministic benchmark (which forces the WORST-case label, an upper bound),
this brackets the real number that the gated bento harness measures end to end.

Network-gated. Defaults target the gemma endpoint from debator/abe.yaml; override
with --base-url / --model or STELE_EW_LLM_URL / STELE_EW_LLM_MODEL.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from benchmarks.evolving_world import _const_llm
from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

DEFAULT_BASE_URL = "http://192.168.1.133:8000/v1"
DEFAULT_MODEL = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"

# (canonical_subject, aspect, [(artifact, value), ...]) oldest-first. The last
# value is the current truth; any earlier value left active is stale.
SCENARIOS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("web tier", "replicas", [
        ("Scaled the web tier up; it now runs 3 replicas behind the load balancer.", "3"),
        ("Traffic grew, so the web tier was scaled to 5 replicas today.", "5"),
    ]),
    ("python", "version", [
        ("Pinned the project to Python 3.11 in pyproject.toml.", "3.11"),
        ("Upgraded the toolchain; Python is now pinned to 3.12 everywhere.", "3.12"),
    ]),
    ("auth token TTL", "seconds", [
        ("Set the auth token TTL to 3600 seconds in the gateway config.", "3600"),
        ("Shortened the auth token TTL; it is now 900 seconds.", "900"),
    ]),
    # value-named (#72): a real model may label the subject after the value.
    ("primary datastore", "engine", [
        ("Standardized the primary datastore on Postgres; all services use Postgres.", "Postgres"),
        ("Migration done: the primary datastore is now MySQL; Postgres is retired.", "MySQL"),
    ]),
]


def openai_llm(model: str, base_url: str, api_key: str = "") -> Callable[[str], str]:
    url = base_url.rstrip("/") + "/chat/completions"

    def _llm(prompt: str) -> str:
        payload = {"model": model, "temperature": 0, "max_tokens": 512,
                   "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urlopen(req, timeout=120) as r:
                body = json.loads(r.read().decode())
        except HTTPError as exc:  # pragma: no cover - network path
            raise RuntimeError(f"LLM server {exc.code}: {exc.read().decode('replace')}") from exc
        return str(body["choices"][0]["message"]["content"])

    return _llm


def _ingest_evolving(stele: Stele, ns: str, canonical: str, aspect: str,
                     steps: list[tuple[str, str]],
                     real_llm: Callable[[str], str] | None) -> None:
    for i, (artifact, value) in enumerate(steps):
        scope = MemoryScope(namespace=ns, session_id=f"s{i}")
        if real_llm is not None:
            llm = real_llm
        else:
            payload = json.dumps([{
                "kind": "fact", "summary": f"{canonical} {aspect} is {value}",
                "subject_label": canonical, "aspect": aspect, "subject_type": "entity",
            }])
            llm = _const_llm(payload)
        stele.extract.from_session(
            transcript=[{"role": "user", "content": artifact}], scope=scope,
            llm=llm, max_windows=1,
        )


def _active_values(stele: Stele, ns: str, values: list[str]) -> list[str]:
    # status_filter=["active"] is load-bearing: memory.list defaults to
    # active+superseded, which would count a CORRECTLY-retired row as stale.
    records = stele.memory.list(MemoryScope(namespace=ns), status_filter=["active"], limit=100)
    texts = [m.text for m in records]
    return [v for v in values if any(v.lower() in t.lower() for t in texts)]


def run_lane(backend: dict[str, object], base_url: str, model: str,
             api_key: str = "") -> dict[str, object]:
    real = openai_llm(model, base_url, api_key)
    rows: list[dict[str, object]] = []
    for idx, (canonical, aspect, steps) in enumerate(SCENARIOS):
        values = [v for _, v in steps]
        out: dict[str, object] = {"scenario": canonical, "current": values[-1]}
        for mode, llm in (("ideal", None), ("real-llm", real)):
            cfg = StashConfig.model_validate(
                {"backend": backend, "extraction": {"enabled": True}})
            stele = Stele(cfg)
            ns = f"ewllm_{mode}_{idx}"
            stele.purge_namespace(ns, dry_run=False)  # hermetic across reruns
            _ingest_evolving(stele, ns, canonical, aspect, steps, llm)
            active = _active_values(stele, ns, values)
            out[mode] = {"active": active, "stale": len(active) > 1}
        rows.append(out)
    n = len(rows)
    real_stale = sum(1 for r in rows if cast_bool(r["real-llm"]))
    ideal_stale = sum(1 for r in rows if cast_bool(r["ideal"]))
    return {
        "benchmark": "evolving_world_llm",
        "model": model,
        "scenarios": rows,
        "ideal_staleness_rate": round(ideal_stale / n, 4) if n else 0.0,
        "real_llm_staleness_rate": round(real_stale / n, 4) if n else 0.0,
    }


def cast_bool(mode_result: object) -> bool:
    return bool(mode_result["stale"]) if isinstance(mode_result, dict) else False


def _print(report: dict[str, object]) -> None:
    print(f"# Evolving-World real-LLM lane  ·  model {report['model']}\n")
    print(f"{'scenario':<22} {'current':<10} {'ideal':<8} real-llm  (active values)")
    for r in report["scenarios"]:  # type: ignore[attr-defined]
        ideal = "stale" if r["ideal"]["stale"] else "clean"
        real = "STALE" if r["real-llm"]["stale"] else "clean"
        print(f"{r['scenario']:<22} {r['current']:<10} {ideal:<8} {real:<8}  "
              f"{r['real-llm']['active']}")
    print(f"\nideal staleness:    {report['ideal_staleness_rate']}  (perfect extraction)")
    print(f"real-LLM staleness: {report['real_llm_staleness_rate']}  "
          f"(extraction-induced, invisible to the deterministic core)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Evolving-world real-LLM lane")
    ap.add_argument("--base-url", default=os.environ.get("STELE_EW_LLM_URL", DEFAULT_BASE_URL))
    ap.add_argument("--model", default=os.environ.get("STELE_EW_LLM_MODEL", DEFAULT_MODEL))
    ap.add_argument("--api-key", default=os.environ.get("STELE_EW_LLM_KEY", ""))
    ap.add_argument("--backend", choices=["postgres", "sqlite"], default="sqlite")
    ap.add_argument("--dsn", default=os.environ.get("STELE_PG_DSN"))
    ap.add_argument("--sqlite-path", default="/tmp/stele_ew_llm.db")
    args = ap.parse_args()

    if args.backend == "postgres":
        if not args.dsn:
            raise SystemExit("postgres backend needs --dsn or STELE_PG_DSN")
        backend: dict[str, object] = {"type": "postgres", "dsn": args.dsn}
    else:
        backend = {"type": "sqlite", "path": args.sqlite_path}

    report = run_lane(backend, args.base_url, args.model, args.api_key)
    _print(report)


if __name__ == "__main__":
    main()

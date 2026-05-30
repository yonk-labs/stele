from __future__ import annotations

import json
import time
from pathlib import Path

from stele import Stele
from stele.core.artifact import estimate_tokens
from stele.interception.wrapper import stash_tool_result


def run(output_dir: Path) -> dict[str, object]:
    stash = Stele.from_config(
        {"interception": {"min_chars": 1000}, "pii": {"enabled": True}}
    )
    payload = {
        "records": [
            {
                "id": i,
                "email": "alice@example.com" if i == 5 else f"user{i}@example.test",
                "status": "active",
                "note": "database migration needs follow up",
            }
            for i in range(500)
        ]
    }
    raw = json.dumps(payload)
    started = time.perf_counter()
    replacement = stash_tool_result(payload, stash=stash, namespace="bench", tool_name="mvp_smoke")
    elapsed_ms = (time.perf_counter() - started) * 1000
    replacement_text = str(replacement)
    report = {
        "suite": "mvp_smoke",
        "input_tokens": estimate_tokens(raw),
        "replacement_tokens": estimate_tokens(replacement_text),
        "token_savings_pct": 1 - (estimate_tokens(replacement_text) / estimate_tokens(raw)),
        "intercept_latency_ms": elapsed_ms,
        "pii_leakage_count": int("alice@example.com" in replacement_text),
        "pass": (
            "stele://bench/" in replacement_text
            and "alice@example.com" not in replacement_text
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(Path("benchmark-output/mvp-smoke")), indent=2))

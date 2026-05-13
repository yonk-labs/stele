#!/usr/bin/env bash
#
# Phase 2 demo: extracts from the five fixture categories and shows the
# resulting ExtractionReport for each. Human-readable proof of behavior.

set -euo pipefail

cd "$(dirname "$0")/.."

.venv/bin/python - <<'PY'
import json
from pathlib import Path

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

FIXTURE_DIR = Path("tests/fixtures/extraction")
stele = Stele(StashConfig())

for fixture_path in sorted(FIXTURE_DIR.glob("*.json")):
    fixture = json.loads(fixture_path.read_text())
    print("=" * 72)
    print(f"category: {fixture['category']}  (expected kind: {fixture['expected_kind']})")
    print("=" * 72)
    for label, samples in (("POSITIVE", fixture["positive"]), ("ABSTENTION", fixture["abstention"])):
        for text in samples:
            print(f"\n[{label}] {text}")
            report = stele.extract.from_text(
                text=text,
                source_refs=["stele://default/demo"],
                scope=MemoryScope(user_id="demo"),
            )
            print(f"  candidates={report.stats.candidate_count}  "
                  f"accepted={report.stats.accepted_count}  "
                  f"rejected={report.stats.rejected_count}")
            for accepted in report.accepted:
                cand = accepted.candidate
                print(f"  ACCEPTED  kind={cand.kind!r:14s} "
                      f"conf={cand.confidence:.2f}  "
                      f"source={cand.lede_source}  path={cand.classifier_path}")
            for rejected in report.rejected:
                print(f"  REJECTED  reason={rejected.reason!r}  "
                      f"kind={rejected.candidate.kind!r}")

stele.close()
print("\ndone.")
PY

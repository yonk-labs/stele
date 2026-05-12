#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export STELE_PG_DSN="${STELE_PG_DSN:-postgresql://yonk:yonk@localhost:55432/stele}"

"$ROOT/scripts/postgres-up.sh"

.venv/bin/pytest tests/contract tests/integration/test_showcase_e2e.py -v
.venv/bin/stele-showcase


#!/usr/bin/env bash
set -euo pipefail

docker compose -f docker-compose.backends.yml up -d --wait

export STELE_PG_DSN="${STELE_PG_DSN:-postgresql://yonk:yonk@localhost:55432/stele}"
export STELE_MARIADB_DSN="${STELE_MARIADB_DSN:-mariadb://yonk:yonk@localhost:53306/stele}"
export STELE_CLICKHOUSE_DSN="${STELE_CLICKHOUSE_DSN:-http://default:@localhost:58123/stele}"

.venv/bin/pytest tests/contract tests/integration/test_showcase_e2e.py -v
.venv/bin/python -m benchmarks.showcase
.venv/bin/python -m benchmarks.recall

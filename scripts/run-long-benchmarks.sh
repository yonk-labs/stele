#!/usr/bin/env bash
set -euo pipefail

docker compose -f docker-compose.backends.yml up -d --wait

export STELE_PG_DSN="${STELE_PG_DSN:-postgresql://yonk:yonk@localhost:55432/stele}"
export STELE_MARIADB_DSN="${STELE_MARIADB_DSN:-mariadb://yonk:yonk@localhost:53306/stele}"
export STELE_CLICKHOUSE_DSN="${STELE_CLICKHOUSE_DSN:-http://default:@localhost:58123/stele}"

repeat="${YMS_LONGRUN_REPEAT:-25}"
content_multiplier="${YMS_LONGRUN_CONTENT_MULTIPLIER:-12}"

.venv/bin/python -m benchmarks.longrun \
  --backends auto \
  --repeat "${repeat}" \
  --content-multiplier "${content_multiplier}"

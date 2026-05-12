#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

docker compose -f docker-compose.postgres.yml up -d --wait postgres

echo "Postgres is ready."
echo "export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele"


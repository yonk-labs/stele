#!/usr/bin/env bash
# Cross-benchmark answer_workflow sweep.
#
# Runs answer_workflow with the 5 stele recall strategies against each
# of LongBench / RAGBench / LongMemEval / LoCoMo using gpt-5-mini as
# both answer model and judge model, on the postgres backend.
#
# Total ~$2-3 of gpt-5-mini API + ~40-60 min wall clock.
#
# Requires:
#   - STELE_PG_DSN env (postgres at :55432)
#   - OPENAI_API_KEY env

set -euo pipefail

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  if [[ -f /home/yonk/yonk-tools/.openai ]]; then
    OPENAI_API_KEY=$(grep '^home_key=' /home/yonk/yonk-tools/.openai | cut -d= -f2-)
    export OPENAI_API_KEY
  else
    echo "OPENAI_API_KEY not set and no key file found" >&2
    exit 2
  fi
fi
if [[ -z "${STELE_PG_DSN:-}" ]]; then
  export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
fi

DATE_DIR=$(date -u +"%Y-%m-%d")
LOG_DIR="benchmarks/runs/${DATE_DIR}/postgres-showcase-logs"
mkdir -p "$LOG_DIR"

# LongBench already ran (answer-workflow-20260521T142700Z). We only need
# the three new benchmarks here. Re-run LongBench by passing it in if you
# want consistency.
BENCHMARKS=(
  ragbench
  longmemeval
  locomo
)

echo "[$(date -u +%H:%M:%S)] cross-benchmark answer_workflow sweep starting"

for src in "${BENCHMARKS[@]}"; do
  echo "[$(date -u +%H:%M:%S)] === $src ==="
  log="$LOG_DIR/answer-workflow-${src}.log"
  if .venv/bin/python -m benchmarks.answer_workflow \
       --backend postgres \
       --scenarios "$src" \
       --judge openai \
       --answer-model gpt-5-mini \
       --judge-model gpt-5-mini \
       --openai-base-url https://api.openai.com/v1 \
       > "$log" 2>&1; then
    echo "[$(date -u +%H:%M:%S)]   ok ($src)"
  else
    rc=$?
    echo "[$(date -u +%H:%M:%S)]   FAIL rc=$rc ($src) — see $log"
  fi
done

echo "[$(date -u +%H:%M:%S)] cross-benchmark sweep complete"

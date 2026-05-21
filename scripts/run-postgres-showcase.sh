#!/usr/bin/env bash
# Run the postgres-only showcase matrix.
#
# Sweeps 9 postgres profiles (pg-keyword, pg-vector, pg-hybrid, pg-hybrid-tight,
# pg-hybrid-wide, pg-hybrid-weighted, pg-graph-smart, pg-graph-hybrid,
# pg-graph-hybrid-rerank) sequentially across the 5 third-party retrieval
# benchmarks. Each profile writes External-<profile>.{json,md} under
# benchmarks/runs/<date>/ and a per-profile log under postgres-showcase-logs/.
#
# Total wall time: ~90-150 min on a developer workstation. Sequential by
# design so the graph profiles don't contend on the raggraph DB.

set -euo pipefail

LOCOMO=${LOCOMO_SAMPLES:-5}
MHR=${MHR_QUERIES:-50}
LME=${LME_QUESTIONS:-8}
LBP=${LONGBENCH_PER_TASK:-12}
RBP=${RAGBENCH_PER_SUBSET:-20}

DATE_DIR=$(date -u +"%Y-%m-%d")
LOG_DIR="benchmarks/runs/${DATE_DIR}/postgres-showcase-logs"
mkdir -p "$LOG_DIR"

PROFILES=(
  pg-keyword
  pg-vector
  pg-hybrid
  pg-hybrid-tight
  pg-hybrid-wide
  pg-hybrid-weighted
  pg-graph-smart
  pg-graph-hybrid
  pg-graph-hybrid-rerank
)

echo "[$(date -u +%H:%M:%S)] postgres-showcase sweep starting"
echo "  budgets: locomo=$LOCOMO mhr=$MHR lme=$LME longbench=$LBP ragbench=$RBP"
echo "  profiles: ${#PROFILES[@]}"

for p in "${PROFILES[@]}"; do
  echo "[$(date -u +%H:%M:%S)] === $p ==="
  log="$LOG_DIR/$p.log"
  if .venv/bin/python -m benchmarks.external \
       --profile "$p" \
       --locomo-samples "$LOCOMO" \
       --mhr-queries "$MHR" \
       --lme-questions "$LME" \
       --longbench-per-task "$LBP" \
       --ragbench-per-subset "$RBP" \
       > "$log" 2>&1; then
    echo "[$(date -u +%H:%M:%S)]   ok ($p)"
  else
    rc=$?
    echo "[$(date -u +%H:%M:%S)]   FAIL rc=$rc ($p) — see $log"
  fi
done

echo "[$(date -u +%H:%M:%S)] postgres-showcase sweep complete"

#!/usr/bin/env bash
# Targeted graph-profile sweep with bounded ingest.
#
# The default run_multihoprag ingests ~6000 corpus docs which makes the
# pg-raggraph projection path take ~30 minutes per profile. This wrapper
# bounds MHR corpus + reduces LongBench/RAGBench budgets so each graph
# profile completes in ~15-20 min.

set -euo pipefail

LOCOMO=${LOCOMO_SAMPLES:-3}
MHR_CORPUS=${MHR_CORPUS:-100}
MHR=${MHR_QUERIES:-30}
LME=${LME_QUESTIONS:-4}
LBP=${LONGBENCH_PER_TASK:-8}
RBP=${RAGBENCH_PER_SUBSET:-12}

DATE_DIR=$(date -u +"%Y-%m-%d")
LOG_DIR="benchmarks/runs/${DATE_DIR}/postgres-showcase-logs"
mkdir -p "$LOG_DIR"

PROFILES=(
  pg-graph-smart
  pg-graph-hybrid
  pg-graph-hybrid-rerank
)

echo "[$(date -u +%H:%M:%S)] graph sweep starting"
echo "  budgets: locomo=$LOCOMO mhr_corpus=$MHR_CORPUS mhr_q=$MHR lme=$LME longbench=$LBP ragbench=$RBP"

for p in "${PROFILES[@]}"; do
  echo "[$(date -u +%H:%M:%S)] === $p ==="
  log="$LOG_DIR/$p.log"
  if .venv/bin/python -m benchmarks.external \
       --profile "$p" \
       --locomo-samples "$LOCOMO" \
       --mhr-queries "$MHR" \
       --mhr-corpus "$MHR_CORPUS" \
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

echo "[$(date -u +%H:%M:%S)] graph sweep complete"

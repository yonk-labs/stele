#!/usr/bin/env bash
# Overnight model-matrix: Mem0 vs stele across answerer models, holding the
# JUDGE constant (gpt-4o) so answerer effects are isolated. Answers:
#   - does a stronger answerer help or hinder the summary (digest)?
#   - does the order of summary/facts/chunks matter, and per-model?
#   - Mem0 vs stele (raw chunks / digest / full context) head-to-head.
#
# Answerers: qwen (local), gemma (local), gpt-4, gpt-4o, gpt-5-mini, gpt-5.
# Judge: gpt-4o (constant). Datasets: LoCoMo (precise) + LongMemEval (synthesis).
# Mem0 runs SERIAL (process-global qdrant lock). NOT set -e (a flaky step must
# not discard earlier saved results). Key via env only (never argv).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
export OPENAI_API_KEY="$(grep '^home_key=' /home/yonk/yonk-tools/.openai | cut -d= -f2-)"
export STELE_PG_DSN="${STELE_PG_DSN:-postgresql://yonk:yonk@localhost:55432/stele}"
OAI="https://api.openai.com/v1"
JUDGE_MODEL="${YMS_JUDGE_MODEL:-gpt-4o}"; JUDGE_BASE="$OAI"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROOT="benchmarks/runs/matrix-${STAMP}"; DATE_DIR="$ROOT/$(date -u +%Y-%m-%d)"
mkdir -p "$DATE_DIR"; LOG="$ROOT/run.log"
log(){ echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }
git rev-parse HEAD >"$ROOT/git-sha.txt" 2>/dev/null || true

# name | answerer base_url | answerer model
ANS=(
 "qwen|http://192.168.1.193:8000/v1|Intel/Qwen3-Coder-Next-int4-AutoRound"
 "gemma|http://192.168.1.133:8000/v1|cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
 "gpt-4|$OAI|gpt-4"
 "gpt-4o|$OAI|gpt-4o"
 "gpt-5-mini|$OAI|gpt-5-mini"
 "gpt-5|$OAI|gpt-5"
)
ORDER_ANS="${YMS_ORDER_ANS:-qwen gpt-4o gpt-5-mini}"   # these also run order perms
DATASETS="${YMS_DATASETS:-locomo longmemeval}"

log "=== model matrix -> $ROOT (judge=$JUDGE_MODEL constant) ==="

# --- stele: Experiment 1 (summary-vs-raw across answerers) + 2 (order perms) ---
for a in "${ANS[@]}"; do
  IFS='|' read -r name base model <<< "$a"
  for ds in $DATASETS; do
    strat="search_first,raw_fetch,digest,adaptive"
    case " $ORDER_ANS " in *" $name "*) strat="$strat,digest_fcs,digest_csf,digest_cfs" ;; esac
    log "STELE $name / $ds / [$strat]"
    args=(-m benchmarks.answer_workflow --judge openai --backend postgres --scenarios "$ds"
          --strategies "$strat" --answer-model "$model" --openai-base-url "$base"
          --judge-model "$JUDGE_MODEL" --judge-base-url "$JUDGE_BASE" --output-root "$ROOT")
    [ "$ds" = longbench ] && args+=(--longbench-per-task 8)
    if $PY "${args[@]}" >>"$LOG" 2>&1; then log "  OK"; else log "  FAIL (continuing)"; fi
  done
done

# --- Mem0: Experiment 3 (per answerer, LoCoMo only — serial) ---
for a in "${ANS[@]}"; do
  IFS='|' read -r name base model <<< "$a"
  log "MEM0 $name / locomo"
  rm -rf /home/yonk/.mem0/migrations_qdrant 2>/dev/null
  if ANSWER_BASE_URL="$base" ANSWER_MODEL="$model" ANSWER_KEY="$OPENAI_API_KEY" \
     JUDGE_BASE_URL="$JUDGE_BASE" JUDGE_MODEL="$JUDGE_MODEL" JUDGE_KEY="$OPENAI_API_KEY" \
     MEM0_OUT="$ROOT/mem0_${name}_locomo.json" MEM0_TAG="$name" \
     /tmp/mem0venv/bin/python /tmp/mem0_runner.py >>"$LOG" 2>&1; then log "  OK"; else log "  FAIL (continuing)"; fi
done

log "consolidating..."
$PY -m benchmarks.external.consolidate_matrix --root "$ROOT" >>"$LOG" 2>&1 || log "  consolidate FAIL"
log "=== MATRIX DONE -> $ROOT ==="

#!/usr/bin/env bash
# Full end-to-end showcase — repeatable, defensible, detailed.
#
# Runs, into one version-stamped run dir:
#   1. showcase  — token reduction + performance + PII, across ALL storage
#                  engines (memory, sqlite, postgres, mariadb, clickhouse)
#   2. recall    — answer-bearing-span retrieval
#   3. longrun   — long-term recall: supersession / as_of / temporal / PII,
#                  across all engines
#   4. answer-workflow (LLM-judged) — answer accuracy vs raw context across
#                  every third-party dataset, answers + judging on two
#                  SEPARATE local models (no self-grading)
#   5. consolidate — cross-benchmark table + FULL-SHOWCASE-REPORT.md
#
# Repeatable: pin models/datasets/sizes via env (defaults below); the git SHA
# and package versions are recorded in the run dir. NOT `set -e`: a flaky later
# lane must never discard an earlier saved result.
#
# Inspect while running:  tail -f benchmarks/runs/full-*/run.log
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python

ANSWER_BASE_URL="${YMS_ANSWER_BASE_URL:-http://192.168.1.193:8000/v1}"
ANSWER_MODEL="${YMS_ANSWER_MODEL:-Intel/Qwen3-Coder-Next-int4-AutoRound}"
JUDGE_BASE_URL="${YMS_JUDGE_BASE_URL:-http://192.168.1.133:8000/v1}"
JUDGE_MODEL="${YMS_JUDGE_MODEL:-cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit}"
DATASETS="${YMS_DATASETS:-synthetic longbench ragbench longmemeval locomo}"
LONGBENCH_PER_TASK="${YMS_LONGBENCH_PER_TASK:-8}"
LONGRUN_REPEAT="${YMS_LONGRUN_REPEAT:-25}"
# longrun builds vector indexes; the shared ClickHouse here has the
# experimental vector-similarity index disabled, so longrun defaults to the
# engines that support it. Set YMS_LONGRUN_BACKENDS=... (or enable
# allow_experimental_vector_similarity_index on ClickHouse) to widen it.
LONGRUN_BACKENDS="${YMS_LONGRUN_BACKENDS:-memory,sqlite,postgres}"
SCENARIO_LIMIT="${YMS_SCENARIO_LIMIT:-}"   # empty = full dataset

# Which real engines to include (memory + sqlite are always covered by the
# showcase). Default: postgres + clickhouse. Add "mariadb" once its `stele`
# database + grants exist. A backend is included iff its DSN env is exported,
# so we unset first, then export only the selected ones.
ENGINES="${YMS_ENGINES:-postgres clickhouse}"
_PG_DSN="${STELE_PG_DSN:-postgresql://yonk:yonk@localhost:55432/stele}"
_MARIADB_DSN="${STELE_MARIADB_DSN:-mariadb://yonk:yonk@localhost:53306/stele}"
_CLICKHOUSE_DSN="${STELE_CLICKHOUSE_DSN:-http://default:@localhost:58123/stele}"
unset STELE_PG_DSN STELE_MARIADB_DSN STELE_CLICKHOUSE_DSN
case " $ENGINES " in *" postgres "*) export STELE_PG_DSN="$_PG_DSN" ;; esac
case " $ENGINES " in *" mariadb "*) export STELE_MARIADB_DSN="$_MARIADB_DSN" ;; esac
case " $ENGINES " in *" clickhouse "*) export STELE_CLICKHOUSE_DSN="$_CLICKHOUSE_DSN" ;; esac

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROOT="benchmarks/runs/full-${STAMP}"
DATE_DIR="${ROOT}/$(date -u +%Y-%m-%d)"
mkdir -p "$DATE_DIR"
LOG="${ROOT}/run.log"
log(){ echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

log "=== full showcase start -> ${ROOT} ==="
git rev-parse HEAD >"${ROOT}/git-sha.txt" 2>/dev/null || true
log "answerer=${ANSWER_MODEL} @ ${ANSWER_BASE_URL}"
log "judge=${JUDGE_MODEL} @ ${JUDGE_BASE_URL}"
log "engines=memory,sqlite,${ENGINES// /,}  datasets=${DATASETS}"

run(){ # label, command...
  local label="$1"; shift
  log "START ${label}"
  if "$@" >>"$LOG" 2>&1; then log "OK    ${label}"; else log "FAIL  ${label} (continuing)"; fi
}

run "showcase (all engines)" "$PY" -m benchmarks.showcase --output-root "$ROOT"
run "recall" "$PY" -m benchmarks.recall --output-root "$ROOT"
run "longrun (${LONGRUN_BACKENDS})" "$PY" -m benchmarks.longrun \
  --backends "$LONGRUN_BACKENDS" --repeat "$LONGRUN_REPEAT" --output-root "$ROOT"

for ds in $DATASETS; do
  args=(-m benchmarks.answer_workflow --judge openai --backend postgres
        --scenarios "$ds"
        --answer-model "$ANSWER_MODEL" --openai-base-url "$ANSWER_BASE_URL"
        --judge-model "$JUDGE_MODEL" --judge-base-url "$JUDGE_BASE_URL"
        --output-root "$ROOT")
  [ "$ds" = "longbench" ] && args+=(--longbench-per-task "$LONGBENCH_PER_TASK")
  [ -n "$SCENARIO_LIMIT" ] && args+=(--scenario-limit "$SCENARIO_LIMIT")
  run "answer-workflow:${ds}" "$PY" "${args[@]}"
done

run "consolidate cross-benchmark" "$PY" -m benchmarks.external.consolidate_answer_workflow \
  --date-dir "$DATE_DIR"
run "consolidate full report" "$PY" -m benchmarks.external.consolidate_full_showcase \
  --date-dir "$DATE_DIR"

log "=== done -> ${DATE_DIR}/FULL-SHOWCASE-REPORT.md ==="
echo "${DATE_DIR}/FULL-SHOWCASE-REPORT.md"

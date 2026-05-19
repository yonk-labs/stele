#!/usr/bin/env bash
# Detached end-to-end driver: finish the MHR + LongMemEval-S compute while
# nobody is watching. Launched via setsid so it re-parents to init and
# survives SSH disconnect AND the Claude session ending.
#
# Robustness choices (unattended = no human to course-correct):
#  - NO `set -e`: a flaky later step must NOT discard an earlier saved result.
#  - MHR (the dispositive graph test) runs FIRST and is fully saved before
#    LongMemEval-S (secondary confirmation) is attempted.
#  - Every step's result is appended to on-disk JSON immediately by the
#    harness; a final summary table is emitted to the log.
#  - The OpenAI key (gpt-5-mini judge) is read from ../.openai at runtime,
#    never written into this script or any file.
#
# Inspect on return:  tail -f benchmarks/external/unattended.log
set -u
cd /home/yonk/yonk-tools/stele-phase6-7 || exit 1

LOG=benchmarks/external/unattended.log
MHR_OUT=/home/yonk/yonk-tools/pg-raggraph/benchmarks/sweep-results/2026-05-19-mhr-sweep.json
LME_OUT=/home/yonk/yonk-tools/pg-raggraph/benchmarks/sweep-results/2026-05-19-lme-sweep.json
DSN1024_HOST=postgresql://postgres:postgres@localhost:5434
PATHWAYS="L0_fts_only,L1_naive,L2_naive_boost_gbf1.5,L3_smart_b0.6,L4_rerank_naive_boost,GP_local_h2,GP_global_h2,GP_hybrid_h2"

export OPENAI_API_KEY="$(grep '^home_key=' /home/yonk/yonk-tools/.openai 2>/dev/null | cut -d= -f2)"

log(){ echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; }

dcount(){ # docs in a namespace in the e768 DB
  uv run python - "$1" <<'PY' 2>/dev/null | tail -1
import asyncio,sys
from pg_raggraph import GraphRAG
ns=sys.argv[1]
async def m():
    async with GraphRAG("postgresql://postgres:postgres@localhost:5434/pg_raggraph_e768",namespace="x") as r:
        row=await r.db.fetch_one("SELECT count(*) n FROM documents WHERE namespace=%(n)s",{"n":ns})
        print((row or {}).get("n",0))
asyncio.run(m())
PY
}

log "=== unattended driver start (pid $$) ==="

# ---- Step 0: wait for the in-flight M_llm_qwen_768 MHR staging ----
log "Step 0: waiting for M_llm_qwen_768 MHR staging to reach 609 docs"
for i in $(seq 1 480); do            # up to 8h @ 60s
  if ! pgrep -f "pgrg_sweep.*--dataset mhr.*M_llm_qwen" >/dev/null 2>&1; then
    n=$(dcount sw_M_llm_qwen_768_mhr)
    if [ "${n:-0}" -ge 600 ]; then
      log "  staging done ($n docs, process exited)"; break
    fi
    log "  staging process gone with only ${n:-0}/609 docs -> re-running stage once"
    PGRG_SWEEP_OUT=$MHR_OUT uv run python -u -m benchmarks.external.pgrg_sweep \
      --phase stage --dataset mhr --ingest M_llm_qwen_768 \
      --samples 150 --mhr-docs 609 >> "$LOG" 2>&1
    break
  fi
  n=$(dcount sw_M_llm_qwen_768_mhr)
  log "  ...$n/609 (staging still running)"
  sleep 60
done

# ---- Step 1: MHR judged graph-ablation sweep (BOTH scorers) ----
log "Step 1: MHR judged sweep (deterministic + gpt-5-mini judge)"
PGRG_SWEEP_OUT=$MHR_OUT uv run python -u -m benchmarks.external.pgrg_sweep \
  --phase sweep --dataset mhr \
  --ingest M_none_768,M_lede_768,M_llm_qwen_768 \
  --samples 150 --mhr-docs 609 --k 20 --judge --only "$PATHWAYS" \
  >> "$LOG" 2>&1 \
  && log "Step 1 DONE" || log "Step 1 ERRORED (MHR data so far is still saved in $MHR_OUT)"

# ---- Step 2: LongMemEval-S — lean confirmation (none/lede, n=20) ----
# Secondary by design (LoCoMo-shaped). llm extraction over big LME haystacks
# is too heavy/fragile to run unattended; none+lede answers the question.
log "Step 2: LongMemEval-S stage (none/lede, n=20)"
PGRG_SWEEP_OUT=$LME_OUT uv run python -u -m benchmarks.external.pgrg_sweep \
  --phase stage --dataset lme --ingest M_none_768,M_lede_768 --samples 20 \
  >> "$LOG" 2>&1 \
  && log "Step 2 stage DONE" || log "Step 2 stage ERRORED"

log "Step 3: LongMemEval-S judged sweep"
PGRG_SWEEP_OUT=$LME_OUT uv run python -u -m benchmarks.external.pgrg_sweep \
  --phase sweep --dataset lme --ingest M_none_768,M_lede_768 \
  --samples 20 --k 20 --judge --only "$PATHWAYS" \
  >> "$LOG" 2>&1 \
  && log "Step 3 DONE" || log "Step 3 ERRORED"

# ---- Step 4: emit a readable summary table to the log ----
log "Step 4: summary"
uv run python - "$MHR_OUT" "$LME_OUT" >> "$LOG" 2>&1 <<'PY'
import json,sys
for path in sys.argv[1:]:
    try:
        d=json.load(open(path))
    except Exception as e:
        print(f"\n[{path}] unreadable: {e}"); continue
    s=[c for c in d.get("cells",[]) if "query_label" in c]
    if not s:
        print(f"\n[{path}] no sweep cells yet"); continue
    print(f"\n===== {path} ({len(s)} cells) =====")
    print(f'{"ingest":18}{"pathway":24}{"rec%":>6}{"judge%":>7}{"MRR":>7}{"h@1%":>6}')
    for c in s:
        print(f'{c["ingest_key"]:18}{c["query_label"]:24}'
              f'{c.get("answer_span_recall_at_k_pct",0):6}'
              f'{c.get("llm_judge_accuracy_pct","-"):>7}'
              f'{c.get("mrr_at_k",0):7}{c.get("hit_at_1_pct",0):6}')
PY

log "=== unattended driver COMPLETE ==="

#!/usr/bin/env bash
set -euo pipefail

base_url="${OPENAI_BASE_URL:-http://192.168.1.193:8000/v1}"
model="${YMS_JUDGE_MODEL:-Intel/Qwen3-Coder-Next-int4-AutoRound}"
scenario_limit="${YMS_ANSWER_WORKFLOW_SCENARIO_LIMIT:-}"

args=(
  -m benchmarks.answer_workflow
  --judge openai
  --openai-base-url "${base_url}"
  --answer-model "${model}"
  --judge-model "${model}"
)

if [[ -n "${scenario_limit}" ]]; then
  args+=(--scenario-limit "${scenario_limit}")
fi

.venv/bin/python "${args[@]}"

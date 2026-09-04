#!/usr/bin/env bash

set -euo pipefail

scenario_file="${1:-benchmarks/multi_turn/data/wtb50.jsonl}"
output_dir="${2:-benchmarks/multi_turn/results}"
scenario_ids="${SCENARIO_IDS:-WTB01}"
model_id="${MODEL_ID:-watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8}"

runner_args=(
  --scenarios "$scenario_file"
  --scenario-ids "$scenario_ids"
  --trajectory-dir "$output_dir/trajectories"
  --model-id "$model_id"
)

if [[ -n "${ENV_FILE:-}" ]]; then
  runner_args+=(--env-file "$ENV_FILE")
fi
if [[ -n "${ROUTER_ENV_PREFIX:-}" ]]; then
  runner_args+=(--router-env-prefix "$ROUTER_ENV_PREFIX")
fi
if [[ -n "${REASONING_EFFORT:-}" ]]; then
  runner_args+=(--reasoning-effort "$REASONING_EFFORT")
fi

uv run stirrup-multi-turn "${runner_args[@]}"
uv run evaluate-multi-turn \
  --scenarios "$scenario_file" \
  --trajectories "$output_dir/trajectories" \
  --output "$output_dir/report.json"


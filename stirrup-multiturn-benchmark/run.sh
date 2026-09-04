#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

scenario_file="${SCENARIO_FILE:-data/wtb50.jsonl}"
scenario_ids="${SCENARIO_IDS:-WTB01}"
model_id="${MODEL_ID:-litellm_proxy/deepseek-v4-flash}"
output_dir="${OUTPUT_DIR:-results}"

runner_args=(
  --scenarios "$scenario_file"
  --scenario-ids "$scenario_ids"
  --model-id "$model_id"
  --trajectory-dir "$output_dir/trajectories"
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
if [[ "${1:-}" == "--dry-run" ]]; then
  runner_args+=(--dry-run)
fi

uv run stirrup-multi-turn "${runner_args[@]}"

if [[ "${1:-}" != "--dry-run" ]]; then
  uv run evaluate-multi-turn \
    --scenarios "$scenario_file" \
    --trajectories "$output_dir/trajectories" \
    --output "$output_dir/report.json"
fi


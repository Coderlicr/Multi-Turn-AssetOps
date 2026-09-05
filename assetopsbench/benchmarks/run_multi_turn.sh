#!/usr/bin/env bash

set -euo pipefail

scenario_source="${1:-src/couchdb/scenarios_data}"
output_dir="${2:-benchmarks/multi_turn/results/two_scenario_pilot}"
scenario_ids="${SCENARIO_IDS:-A16-06,WTB01}"
model_id="${MODEL_ID:-tokenrouter/z-ai/glm-5.3-free}"
temperature="${TEMPERATURE:-0}"
max_turns="${MAX_TURNS:-12}"

runner_args=(
  --scenarios "$scenario_source"
  --scenario-ids "$scenario_ids"
  --trajectory-dir "$output_dir/trajectories"
  --model-id "$model_id"
  --temperature "$temperature"
  --max-turns "$max_turns"
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
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  runner_args+=(--dry-run)
fi

uv run stirrup-multi-turn "${runner_args[@]}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  exit 0
fi

uv run evaluate \
  --scenarios "$scenario_source" \
  --trajectories "$output_dir/trajectories" \
  --scorer-default static_json \
  --reports-dir "$output_dir/static-json-report"

uv run python -m evaluation.poor_performance_report \
  --input "$output_dir/static-json-report/_aggregate.json" \
  --output "$output_dir/poor-performance.json"

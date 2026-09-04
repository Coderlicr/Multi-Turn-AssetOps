#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

uv sync --group dev
uv run build-multi-turn-data
uv run pytest -q
uv run check-stirrup-mcp
./run.sh --dry-run
uv run evaluate-multi-turn \
  --scenarios data/wtb50.jsonl \
  --trajectories poc/trajectories \
  --output /tmp/stirrup-multiturn-benchmark-poc-report.json >/dev/null

echo "Standalone benchmark checks passed."

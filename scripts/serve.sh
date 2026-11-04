#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/reachy-local ]]; then
  echo "Run ./scripts/setup.sh once before starting the server." >&2
  exit 1
fi
exec .venv/bin/reachy-local serve "$@"

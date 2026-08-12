#!/usr/bin/env bash
set -euo pipefail

export SHIPIT_RUN_LIVE_TESTS=1
exec "$(dirname "$0")/../.venv/bin/python" -m pytest -q -s \
  "$(dirname "$0")/../tests/live/test_advanced_agent_live.py" "$@"

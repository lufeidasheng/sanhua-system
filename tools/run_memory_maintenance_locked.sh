#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
  PY="${VIRTUAL_ENV}/bin/python3"
else
  PY="$(command -v python3)"
fi

echo "========================================================================"
echo "RUN locked memory maintenance"
echo "========================================================================"
echo "ROOT=$ROOT"
echo "PY=$PY"

cd "$ROOT"

"$PY" tools/run_memory_maintenance.py --root "$ROOT"
"$PY" tools/lock_session_summary_order_v1.py --root "$ROOT"
"$PY" tools/compact_action_log_counts_v1.py --root "$ROOT"
"$PY" tools/merge_test_degraded_into_main_v1.py --root "$ROOT"
"$PY" tools/compact_recent_messages_anchor_latest_v1.py --root "$ROOT"

echo "========================================================================"
echo "locked memory maintenance finished"
echo "========================================================================"
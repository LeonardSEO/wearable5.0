#!/bin/sh
# One command for the own-strap study: every metric check, every rule and the head-to-head with NOOP, over your data.
#
# It does NOT touch the strap. Acquire data first:
#   1. Wear the strap; let the official WHOOP app sync.
#   2. Save WHOOP's values with re/whoop_api_fetch.py (an API snapshot folder).
#   3. Re-read the same nights raw from the strap with re/refetch.sh (re/REREAD_HISTORY.md), into the data folder.
#
# Usage: re/pipeline.sh <data-folder> <api-snapshot-folder> [whoop-export.zip]
#   e.g. re/pipeline.sh whoop5-data/own_strap whoop5-data/own_strap/api/20261119-170740 my_whoop_data.zip
set -eu
DATA=$1
API=$2
EXPORT=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-"$HERE/../../.venv/bin/python"}

echo "============================================================"
echo " 1. Claim board: decoder, R-R, R21, R26 and every night against WHOOP's API values"
echo "============================================================"
"$PY" -I "$HERE/validate_own_strap.py" "$DATA" --api="$API" | sed -n '1,/## Frame kinds/p' | sed '$d'
echo
echo "============================================================"
echo " 2. Sleep-need rules and the formulas in use (re/score_formulas.py)"
echo "============================================================"
"$PY" -I "$HERE/api_checks.py" "$API"
if [ -n "$EXPORT" ]; then
  echo
  echo "============================================================"
  echo " 3. Every claim from the export and API, rechecked"
  echo "============================================================"
  "$PY" -I "$HERE/verify_findings.py" "$EXPORT" "$API" "$DATA"
fi
echo
echo "============================================================"
echo " 4. Head-to-head with NOOP's own scorers (needs re/noop_scores built)"
echo "============================================================"
if [ -x "$HERE/noop_scores/.build/release/noop-scores" ]; then
  "$PY" -I "$HERE/noop_compare.py" "$API" "$DATA"
else
  echo "   skipped: build re/noop_scores first (see re/noop_compare.py)"
fi
echo
echo "Done. Per-night detail (local only): $DATA/REPORT.md and $DATA/report.json."

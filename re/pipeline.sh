#!/bin/sh
# One command for the own-strap study: validate every claim, then fit the scores, over your data + WHOOP export.
#
# It does NOT touch the strap. Acquire data first (both are quick):
#   1. Wear the strap for the night(s); let the official WHOOP app sync, and export your data from the app.
#   2. Re-read the same night(s) raw from the strap with re/refetch.sh (re/REREAD_HISTORY.md), into the data folder.
# Then drop the export .zip in the data folder and run this.
#
# Usage: re/pipeline.sh <data-folder> <whoop-export.zip>
#   e.g. re/pipeline.sh whoop5-data/own_strap my_whoop_data_2026_11_05.zip
set -eu
DATA=$1
EXPORT=$2
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-"$HERE/../../.venv/bin/python"}

echo "============================================================"
echo " 1. Claim board (decoder, R-R, R21, R26, and the night checks)"
echo "============================================================"
"$PY" -I "$HERE/validate_own_strap.py" "$DATA" | sed -n '1,/## Frame kinds/p' | sed '$d'
echo
echo "   SpO2 is the flagship: it needs 5 paired nights (ours + WHOOP). The row above shows how many are paired;"
echo "   REPORT.md in the data folder has the per-night SpO2 table."
echo
echo "============================================================"
echo " 2. Recovery / sleep score fit (needs ~20 cycles of WHOOP history)"
echo "============================================================"
"$PY" -I "$HERE/score_model.py" "$EXPORT"
echo
echo "============================================================"
echo " 3. Day strain (HR zones -> TRIMP -> log fit, per WHOOP cycle)"
echo "============================================================"
"$PY" -I "$HERE/strain_model.py" "$DATA" "$EXPORT" | sed -n '/cycle start/,$p'
echo
echo "Done. Full SpO2 and metric detail: $DATA/REPORT.md and $DATA/report.json."

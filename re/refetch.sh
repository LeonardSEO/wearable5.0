#!/bin/sh
# Resumable re-read: relaunch the fetch until it reaches the stop time, so a dropped BLE link just continues.
# Usage: re/refetch.sh <WhoopProbe.app> <venv-site-packages> <out> "<start>" "<stop>" [restore PAGE:WRAP]
set -eu
APP=$1; SP=$2; OUT=$3; START=$4; STOP=$5; RESTORE=${6:-}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
for attempt in $(seq 1 40); do
  RESUME=""; [ "$attempt" -gt 1 ] && RESUME="--resume"
  REST=""; [ -n "$RESTORE" ] && REST="--restore $RESTORE"
  open -W --stdout "$OUT/run.log" --stderr "$OUT/run.log" --env PYTHONPATH="$SP" "$APP" --args \
    "$HERE/probe_read_pointer.py" fetch --span "$START" "$STOP" $RESUME $REST --out "$OUT" || true
  tail -n 40 "$OUT/run.log" | grep -q "reached stop\|restored to" && { echo "done on attempt $attempt"; break; }
  echo "attempt $attempt ended early; retrying"; sleep 5
done

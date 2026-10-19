#!/usr/bin/env bash
# Download the public 5/MG v20 corpus donated in ryanbr/noop#1992 into re/corpus/ (gitignored).
# Sensor payloads only, no identifiers, per the donor. Not redistributed by this repository.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p corpus
gh gist clone c452899c5b7dd224e87871f28a5554d1 corpus/v20_frames
gh gist clone 8ee72b4e9b0c9b1578792e70ee1fe3c5 corpus/v20_ground_truth
echo "python re/analyze_v20_optical.py re/corpus/v20_frames/rejected_history.jsonl re/corpus/v20_ground_truth/ground_truth_window.csv"

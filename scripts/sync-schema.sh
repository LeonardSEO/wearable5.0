#!/usr/bin/env bash
# Copy the canonical schema into every consumer, then regenerate the parity vectors.
set -euo pipefail
cd "$(dirname "$0")/.."
cp protocol/whoop5_protocol.json python/whoop5/whoop5_protocol.json
cp protocol/whoop5_protocol.json Packages/Whoop5Protocol/Sources/Whoop5Protocol/Resources/whoop5_protocol.json
python3 -I python/gen_golden.py
cp fixtures/golden.json Packages/Whoop5Protocol/Tests/Whoop5ProtocolTests/Resources/golden.json

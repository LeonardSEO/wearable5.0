"""Generate fixtures/golden.json: frames + the Python reference decode, for cross-language parity.

Synthetic frames only, plus the three real frames published by ryanbr/noop. Re-run after any decoder
change; the Swift tests fail until their decode matches this file.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from tests.test_decode import REAL_END, REAL_R18, REAL_R26  # noqa: E402
from whoop5 import synth  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402

KEEP = ["packet_type", "layout", "record_index", "unix_s", "heart_rate", "rr_ms", "skin_temp_c", "step_counter",
        "band_state", "accel_x", "gyro_z", "samples", "event", "event_name", "meta_type", "trim_cursor",
        "end_token_hex", "command", "result", "temp_aux1_c", "burst_counter", "sample_count", "quality", "lead_i"]

frames = {
    "synthetic_r18": synth.r18(),
    "synthetic_r18_cold": synth.r18(skin_raw=0),
    "synthetic_r21": synth.r21(5),
    "synthetic_r26": synth.r26(),
    "synthetic_realtime_hr": synth.realtime_hr(61, (1000, 1100)),
    "synthetic_data_range": synth.data_range(120, 100),
    "synthetic_data_range_wrap": synth.data_range(5, 131070, newest=0xFFFFFFFF),
    "synthetic_event_wrist_on": synth.event(9),
    "synthetic_ecg_r17": synth.ecg_r17(),
    "synthetic_ecg_r16": synth.ecg_r16(),
    "synthetic_short_history_complete": synth.short_metadata(3),
    "real_r18_noop": bytes.fromhex(REAL_R18),
    "real_r26_noop": bytes.fromhex(REAL_R26),
    "real_history_end_noop": bytes.fromhex(REAL_END),
}

out = []
for name, raw in frames.items():
    d = decode_frame(raw)
    exp = {k: d[k] for k in KEEP if k in d}
    if "fields" in d:
        exp["pages_behind"] = d["fields"]["pages_behind"]
        exp["newest_unix"] = d["fields"]["newest_unix"]
    out.append({"name": name, "hex": raw.hex(), "expected": exp})

path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "golden.json")
with open(path, "w") as f:
    json.dump(out, f, indent=1, sort_keys=True)
print(f"wrote {len(out)} vectors to {os.path.normpath(path)}")

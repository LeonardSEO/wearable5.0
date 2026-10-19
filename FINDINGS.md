# WHOOP 5.0 / MG BLE protocol — findings

_Last updated 2026-10-19._ Independent interoperability research; not affiliated with WHOOP, Inc.
Every claim carries an evidence tier (defined in `protocol/whoop5_protocol.json`):
**corpus** (verified here on real 5/MG frames), **apk** (static analysis of the official Android app
5.473.0, facts only), **noop / goose / johga** (community sources), **constructed** (arithmetic only).

This repository did **not** have a WHOOP 5.0 strap. Everything marked *corpus* was verified on frames
other owners published: 31,489 CRC-valid 5/MG frames harvested from public repositories, issue
attachments and two HCI captures (an iOS PacketLogger capture of the official app syncing overnight,
and an Android btsnoop from a WHOOP MG). Raw data is not redistributed here; the tools in `re/` rebuild
the corpus locally (see `re/README.md`). WHOOP 4.0 material was excluded file by file.

## Status at a glance

| Capability | Status | Tier |
|---|---|---|
| GATT map, six device families | ✅ | apk |
| Format-1 envelope: CRC16-Modbus header, CRC32 body, padding | ✅ byte-exact | corpus |
| CLIENT_HELLO and history ACK construction | ✅ byte-identical to hardware-proven frames | corpus |
| Command table: 82 from the app + 5 firmware-only from NOOP; destructive set | ✅ | apk + noop |
| Complete event table (58 events) and packet-type table (35–56) | ✅ | apk |
| GET_DATA_RANGE: dual response, page cursors, newest clock | ✅ field-exact, confirmed on 589 real replies | corpus + apk |
| History START / END / COMPLETE and the 8-byte END token | ✅ | corpus |
| Live HR + R-R (packet 40) | ✅ | noop + corpus |
| **R-R unit: milliseconds, not 1/1024 s** (R18 and 0x2A37; packet 40 likely) | ✅ §8 (independent confirmation of NOOP #2046/#2195) | corpus |
| R18 biometric summary: HR, R-R, gravity, steps, skin temp, band state | ✅ one full night described (§12) | corpus (20,274 records) + noop + johga |
| R16/R17 MG ECG records | ✅ structure, 81 real records | corpus + noop |
| Event header, payloads, BATTERY_LEVEL payload | ✅ | corpus |
| Console log text | ✅ decoded and joined | corpus |
| Official app sync cadence and feature-flag values | ✅ **new** — §10 | corpus |
| R20 optical: which channels carry the pulse | ✅ **new** — see §4 | corpus |
| R20 optical → heart rate that tracks a varying reference | ✅ **new**, r ≈ 0.8, MAE ≈ 2 bpm | corpus |
| R26 compact optical: contiguity and heart rate | ✅ **new**, r = 0.95, MAE 1.4 bpm over 17 night bursts — §11 | corpus |
| R21 six-axis IMU, R22 v9 | ✅ structure | noop |
| **SpO₂** | 🧪 **decoded, experimental**: R18 byte 82 in 30 s windows every 20 min during sleep; one value per window via `spo2_windows` — §13 | corpus |
| Overnight HRV (RMSSD) | 🧪 experimental helper `rmssd_ms` on R18 R-R | corpus |
| Sleep stages, recovery, strain | ⚫ cloud-side in the official app (§3) — must be computed locally | apk |

## 1. Device families and GATT (apk)

The official app distinguishes six families. Two share the **classic** inner codec:

| Family | Service UUID | Inner codec |
|---|---|---|
| GEN_4 (WHOOP 4.0) | `61080001-8d6d-82b8-614a-1c8cb0f8dcc6` | classic |
| **MAVERICK (WHOOP 5.0 / MG)** | `fd4b0001-cce1-4033-93ce-002d5875f58a` | classic |
| GOOSE | — | classic |
| PUFFIN (battery pack) | `11500001-6215-11ee-8c99-0242ac120002` | puffin |
| MONUMENT | `8a580001-2fe8-4796-9267-b87a2b0c8234` | "Rev2" |
| SYMPHONY | `59830001-5955-419b-bb8d-c8262926af23` | "Rev2" |

Characteristics on `fd4b…`: `0002` command write, `0003` command responses, `0004` events,
`0005` data, `0007` memfault. The `1150…` service seen next to a 5/MG belongs to the battery pack.
The Rev2 families use a different envelope; do not apply 5/MG offsets to them.

## 2. Envelope and inner packets (corpus + apk)

```
[0]  AA           start
[1]  01           format 1
[2]  u16 LE       declared length = frame length − 8
[4]  u8           destination   (requests 00, strap replies 01)
[5]  u8           source        (requests 01, strap replies 00)
[6]  u16 LE       CRC16-Modbus (poly 0xA001, init 0xFFFF) over [0,6)
[8]  …            inner packet: [type][seq][cmd/layout]…, zero-padded to a multiple of 4
[-4] u32 LE       CRC32 (zlib) over [8, end−4)
```

All 1,127 frames of the donated corpus validate under these rules. Large records (R20 is 2,140
bytes) span many BLE notifications; only the first fragment starts with `AA 01`.

Inner command response (type 36): `[36][seq][cmd][origin seq][result][body…]`, so the body starts at
frame offset 13. Result codes: 0 failure, 1 success, 2 pending, 3 unsupported.

Data records (types 43/47): `[type][layout][marker][record index u32][unix u32][subsec u16]` at frame
offsets 8/9/10/11/15/19. The app reads only this header (plus one heart-rate byte per layout) on the
phone; see §3.

## 3. What the official app does on the phone (apk)

- It queries **GET_DATA_RANGE before every history sync** and logs the backlog in pages. That
  command is flagged as dual-response: a PENDING reply, then SUCCESS with the body.
- It decodes record headers and uploads record bodies per layout revision, tracking per-revision
  sequence gaps. It does **not** compute SpO₂, respiratory rate, skin temperature, sleep stages,
  recovery or strain on the phone. Those arrive from the server as display values.
- Consequence: there is no phone-side algorithm to copy. Sleep, recovery and SpO₂ must be built
  locally from R18 / R20 / R21, which is the work §4–§5 starts.

### GET_DATA_RANGE (34) final body (65 bytes)

| Body offset | Field | Tier |
|---:|---|---|
| 0 | revision 1 | noop |
| 5 | read page | noop |
| 9 | write page | apk + noop |
| 13 | trim (acknowledged) page | apk + noop |
| 21 | ring capacity in pages | apk + noop |
| 57 / 61 | clock of the last written page (seconds / fraction) | noop |

**Confirmed (corpus):** 589 complete replies from 21 public capture sessions (NOOP issue attachments,
Asherlc/dofek, tanarchytan/whoop-rs). The body is 65 bytes plus 2 padding bytes. The u32 at offset 57
is a plausible Unix time in all 589; when the backlog is 0 it equals the trim-side clock in 286 of
286; capacity is 131,072 pages in every reply; one 4 KB page holds a median 13.6 s of history.

Backlog = `write − trim`, wrapping through capacity (the app's own formula). Clock sentinels `0` and
`0xFFFFFFFF` mean "no usable time". The 5/MG reply has a real newest-page clock at a fixed offset,
so no byte-scan for timestamps is needed.

## 4. R20 optical: the pulse channels (corpus, new)

Corpus: 1,034 unique consecutive seconds of R20 from one 5/MG (firmware 50.39.1.0), with the strap's
own 1 Hz HR as reference. The reference moves between 51 and 86 bpm. Script:
`re/analyze_v20_optical.py`; full output in `re/results/v20_optical_noop1992.txt`.

Block configuration was constant across the window:

| Block | Slot A (source, drive, detector) | Slot B | Samples/s | Role (this work) |
|---|---|---|---|---|
| 0 | src 1, drive 750, det 3 | src 4, drive 1500, det 4 | 25 | **pulse** |
| 1 | src 3, drive 12750, det 1 | src 4, drive 0, det 2 | 0 (25 in one 21 s burst) | intermittent, see §5 |
| 2 | src 2, drive 3400, det 1 | src 4, drive 0, det 2 | 0 (25 in the same burst) | intermittent, see §5 |
| 3 | src 2, drive 0, det 3 | src 4, drive 0, det 4 | 25 | **dark / ambient** |
| 4 | src 2, drive 200, det 3 | src 4, drive 0, det 1 | 25 | **pulse** |

Heart rate from time-domain beat detection (band-pass 0.6–3.3 Hz, 10 s windows, median inter-beat
interval) against the reference:

| Channel | Perfusion (AC/DC) | r vs reference | MAE | Shuffled-record control r / MAE |
|---|---:|---:|---:|---:|
| 0A | 0.0183 | **0.80** | **2.0 bpm** | −0.01 / 16.5 |
| 0B | 0.0094 | **0.82** | **1.8 bpm** | 0.03 / 21.0 |
| 4A | 0.0015 | **0.77** | **1.9 bpm** | −0.02 / 10.9 |
| 4B | 0.0029 | **0.74** | **2.1 bpm** | −0.07 / 12.6 |
| 3A / 3B | ~0.02 of a ~200-count floor | ≈0 | ≈75 | ≈0 / ≈73 |

The control keeps each one-second record intact but shuffles their order. It collapses to r ≈ 0, so
the result is not the one-second record-boundary artifact that sank an earlier PPG→HR attempt
(NOOP #194). Limits: one wearer, one ~17-minute evening window, a reference that is itself the
strap's optical HR. The block 3 drive-0 channel is a dark reference suitable for ambient subtraction.

Practical use: a client can bank heart rate from R20 records it currently rejects, which is what
leaves NOOP's iOS history frontier open (#1992). Ship it as instrumentation first, per NOOP's own rule
for derived signals.

## 5. SpO₂: what is and is not on the wire

SpO₂ itself is reported in R18 byte 82 (§13, found later in an overnight capture). The R20 observations below
still stand.

- The phone app computes no SpO₂ (§3); the strap does, and reports it in R18 byte 82 (§13).
- Firmware console text recovered by NOOP reads *"generated a valid SPO2 during sleep"*, so the strap
  runs an oxygen computation itself, intermittently.
- In this corpus, blocks 1 and 2 (the two highest LED drives, 12750 and 3400) are populated for one
  contiguous 21-second burst and empty otherwise. That matches an intermittent two-wavelength
  measurement window. In that burst, block 1 slot A has AC/DC 0.0011 and block 2 slot A 0.0041.
- **Not established:** which source is red and which is infrared, the calibration curve, or where (if
  anywhere) the strap's own result is emitted. Do not derive SpO₂ from this. What would settle it: an
  overnight corpus containing several bursts plus the owner's exported WHOOP SpO₂ for the same nights.

## 6. What still needs a strap or more donated data

| NOOP README limit | Blocker | What closes it |
|---|---|---|
| Sleep detection / stages | One full night of R18 described (§12): band state, HR dip, motion, temperature; no R21 and no stage reference | A night with R21 and a sleep reference (watch stages or WHOOP export) |
| Skin temperature consistency | R18 `u16@73 / 100 °C` agrees across NOOP, Johga and goose and gives a plausible overnight curve (31.4–35.0 °C) | R18 from more firmware versions, with the WHOOP export |
| SpO₂ | Decoded, experimental (§13) | Comparison with the WHOOP app's SpO₂ for a captured night; more wearers |
| Overnight HRV | Solved for R18: 92 % of beats delivered overnight, R-R in ms (§8, §12); `rmssd_ms` helper | Comparison with the WHOOP export's HRV |
| Respiration | No field identified | Overnight data plus the WHOOP export |
| Bonding refusals on some Android phones | Strap refuses SMP pairing (NOOP #1635) | Hardware investigation |

## 8. R-R intervals are in milliseconds (corpus)

This library first converted R-R as 1/1024 s ticks (the Bluetooth Heart Rate profile unit), as early
NOOP builds did. NOOP corrected this in #2046 / #2195 after the discussion in #1505, using the same
public iOS capture; the analysis below reached the same result independently. Script: `re/analyze_rr_unit.py`; result: `re/results/rr_unit.txt`.

1. In both HCI captures (iOS and MG), raw R18 R-R values are identical beat for beat to the raw R-R
   values in the strap's standard 0x2A37 Heart Rate Measurement notifications (mean difference 0.00
   over 25 consecutive beats).
2. Summing those 0x2A37 values over 93 windows in which every beat was reported, against the phone's
   own capture clock: **0.9992** of the elapsed time when read as milliseconds, 0.976 as 1/1024 s.
3. R18 alone, 203 full-coverage minutes overnight: **0.9986** as ms, 0.975 as 1/1024 s.

So the WHOOP 5/MG sends R-R in milliseconds in R18 and, contrary to the BLE specification, in 0x2A37.
Packet 40 follows on moderate evidence (HR × RR / 60000 = 0.997 over 234 live samples). The decoders
now return the raw value as ms.

## 9. MG ECG, events, console (corpus)

- **R16 / R17** (MG ECG, layouts after NOOP `PROTOCOL_ECG.md`): all 25 real R16 records (500 samples,
  18-bit two's complement, lead counts 10–11) and 56 R17 records (100 i16 samples) decode within
  capacity, with quality codes 1–3. Physical scale and sample rate remain unestablished.
- **Events** carry subsec (u16 @16), payload length (u16 @18) and the payload from @20 (consistent on
  2,377 of 2,380 real frames). `BATTERY_LEVEL`: state of charge in tenths @1 and millivolts @5; ten real
  events run from 49.9 % at 3,833 mV to 99.9 % at 4,382 mV. Eight event numbers seen on the wire have no
  name in the app's table (48, 61, 62, 110, 112, 115, 116, 120).
- **Console** (type 50): `[0x01][text fragment][NUL]`, joined in arrival order. 1,423 reconstructed
  lines (`re/results/console_inventory.txt`). The firmware logs `SLEEPFLAG` transitions with the labels
  WAKE / STILL / SLEEP / UP, the same vocabulary as R18 band state, plus wear-detection state changes and
  per-pull history statistics.
- **GET_CLOCK_DEPRECATED** (11) replies with Unix seconds at body offset 0 (49 real replies).
- Running both decoders over the corpus found and fixed a Swift crash on valid frames shorter than a
  type's fixed header, and two Python reads into CRC bytes. Swift and Python now agree on 30,559 real
  frames (190,883 field checks).

## 10. What the official app sends (corpus, new)

From the iOS capture of the official app (5 h overnight; `re/analyze_official_sync.py`):

- A history round every **~600 s**: SEND_HISTORICAL_DATA → GET_DATA_RANGE → SEND_HISTORICAL_DATA →
  one HISTORICAL_DATA_RESULT per chunk → often ABORT_HISTORICAL_TRANSMITS. 40 rounds, 459 ACKs.
- The app enumerates both key tables and writes **all 16 feature flags** with ASCII values: `'1'` only
  for `enable_r22_v4_packets` and `enable_passive_strap_fit_gen5`, `'2'` for the other 14. Keys by
  index and values are in the schema (`feature_flags`). Device-config keys (7): `sigproc_wear_detect`,
  `enable_rfid`, `max_collection_backlog`, `cont_collection_mode`, `whoop_live_hr_in_adv_ind_pkt`,
  `whoop_live_2_hrm_devices`, `enable_raw_data_w_ecg`.
- The app also sent DISABLE_ALARM, GET_HELLO, GET_ADVERTISING_NAME and one REBOOT_STRAP.

## 11. R26 compact optical (corpus, new)

`re/analyze_r26.py`, `re/results/r26_analysis.txt`. During the captured night the strap records a
40-second R26 burst roughly every 19 minutes (17 bursts). Within bursts, records are contiguous at
25 samples/s (boundary step equals the in-record step; 0 clipped deltas in 17,112). Heart rate from the
R26 waveform against R18 heart rate: **r = 0.95, MAE 1.4 bpm** per burst over 17 bursts spanning
46–66 bpm (window level r = 0.82, MAE 2.7); a shuffled-record control fails (MAE 27.7). One night, one
wearer.

## 12. One full night of R18 (corpus, new)

`re/analyze_overnight_r18.py`, `re/results/overnight_r18.txt`: 18,602 consecutive records,
22:57–04:07 UTC, no gaps. Band state is SLEEP for 99.5 % of records and turns UP at the end with a
motion spike. Heart rate falls from ~62 to ~47 bpm and rises again on waking; 5-minute RMSSD ranges
47–102 ms (whole night 73.5 ms, artefact-filtered); 92 % of the expected beats are present as R-R.
Skin temperature rises from 31.9 to 34.9 °C over the night and the two auxiliary channels track it.
This describes the signals; it is not a sleep-stage or recovery validation.

## 13. SpO₂ in R18 byte 82 (corpus, new — experimental)

`re/analyze_r18_b82_windows.py`, `re/results/r18_b82_windows.txt`, `re/results/spo2_windows_ios_night.txt`.

The strap measures SpO₂ itself during sleep and reports it in R18 byte 82:

- Byte 82 is 0 in every record (18,152 of 18,152) except inside **15 windows of exactly 30 s, starting
  exactly every 1,200 s** (xx:05:37, xx:25:37, xx:45:37), all in band state SLEEP. The status words at
  77/79 change in the same records. The daytime MG session has no windows.
- Inside a window each second holds either a **SpO₂ percentage (87–100)** that moves smoothly from
  second to second (for example `97 96 96 96 96 97 97 97 98 97`) or a status code (160, 128, 32, 16, 1, …)
  when the strap has no valid reading that second.
- This matches the firmware's own console message *"generated a valid SPO2 during sleep"*, and NOOP's
  tri-mode reading of byte 82 (`spo2_candidate_82`: 70–100 = %, high-bit values = status).

Decoding: `spo2_percent` is byte 82 when it is 70–100, else nil. `spo2_windows()` (Python) /
`Whoop5Experimental.spo2Windows` (Swift) gives one value per window: the median of its valid seconds,
with at least 5 valid seconds. On the captured night that yields **7 windows of 93–99 % (mean 96 %)**;
the other 8 windows held only status codes. Experimental: one night and one wearer so far, and not yet
compared with the WHOOP app's SpO₂ for the same night.

## 14. R20 heart rate on a second session (corpus, negative)

`re/analyze_r20_hr_sessions.py`, `re/results/r20_hr_sessions.txt`. On a second R20 session (NOOP #26:
92 minutes, 36 % record coverage, awake, HR 85–89 bpm) with only 15 live-HR reference points
(converted with the time zone the log states), the R20 estimate does **not** match (MAE 12–28 bpm).
R20 heart rate therefore stays validated on one resting session only. Block configuration differs
between the sessions (block 2 drive 3400 vs 4250), and the two-channel burst does not occur in the
second one (`re/results/r20_config_bursts.txt`).

## 15. Sources

- Official WHOOP Android app 5.473.0 (static analysis for interoperability; nothing reproduced).
- [ryanbr/noop](https://github.com/ryanbr/noop) protocol docs, test vectors and the #1992 corpus
  donated by @p3LZ3r.
- [b-nnett/goose](https://github.com/b-nnett/goose) (archived).
- [OpenStrap/protocol](https://github.com/OpenStrap/protocol).
- [Johga/Gadgetbridgefork](https://codeberg.org/Johga/Gadgetbridgefork/src/branch/whoop).
- [Gadgetbridge #5731](https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/5731) (tazjin).
- [johnmiddleton12/wearable](https://github.com/johnmiddleton12/wearable), the WHOOP 4.0 counterpart
  this repository is modelled on.

# WHOOP 5.0 / MG BLE protocol — findings

_Last updated 2026-11-05._ Independent interoperability research; not affiliated with WHOOP, Inc.
Every claim carries an evidence tier (defined in `protocol/whoop5_protocol.json`):
**own strap** (one owner's strap against that owner's WHOOP export), **corpus** (real 5/MG frames other
owners published), **apk** (static analysis of the official Android app 5.473.0 and 5.475.0, facts only),
**noop / goose / johga** (community sources), **constructed** (arithmetic only).

The corpus is 31,489 CRC-valid 5/MG frames from public repositories, issue attachments and two HCI captures.
The own-strap data is 1,066,054 unique frames from one WHOOP 5.0. Raw data is not redistributed here; the tools
in `re/` rebuild the corpus locally (see `re/README.md`). WHOOP 4.0 material was excluded file by file. Section
numbers are stable because outside links use them; there is no §7.

## Status at a glance

**Proven** means the evidence settles the claim within the scope stated in the row. **Measured** means real numbers
exist but the bar fixed in advance (`CRITERIA` in `re/validate_own_strap.py`, 5 paired nights) is not reached yet.
**Failed** means it was tested and did not hold. **Open** means it is not settled.

| Capability | Verdict | Evidence | Tier |
|---|---|---|---|
| GATT map, six device families | Proven | §1 | apk |
| Format-1 envelope: CRC16-Modbus header, CRC32 body, padding | Proven | byte-exact on every corpus frame, §2 | corpus |
| CLIENT_HELLO and history ACK construction | Proven | a full session on the owner's strap, §17 | own strap |
| Command table: 82 from the app + 5 firmware-only from NOOP; destructive set | Proven | same in app 5.473.0 and 5.475.0 | apk + noop |
| Event table (58 events) and packet-type table (35–56) | Proven | §9 | apk |
| GET_DATA_RANGE: dual response, page cursors, newest clock | Proven | 589 real replies, §3 | corpus + apk |
| History START / END / COMPLETE and the 8-byte END token | Proven | §17 | corpus + own strap |
| Live HR + R-R (packet 40) | Proven | §8 | noop + corpus |
| **R-R unit is milliseconds, not 1/1024 s** | Proven | 3 independent measures, 0.996 over 166,882 records on the owner's strap, §8, §18 | corpus + own strap |
| R18 biometric summary: HR, R-R, gravity, steps, skin temp, band state | Proven | 0 undecodable in 547,041 own-strap records, §12, §18 | corpus + own strap |
| R21 accelerometer scale, 4096 LSB/g | Proven | 1.003 g over 71,019 still seconds, §18 | own strap |
| **Re-reading trimmed history** | Proven on one strap | 4 spans complete, restored trim holds, app syncs on from a moved trim, §17 | own strap |
| **Recovery, strain and sleep scores are computed on WHOOP's servers** | Proven | no formula in the app, §3 | apk |
| Official app sync cadence and feature-flag values | Proven | §10 | corpus |
| R20 channels that carry the pulse | Proven | shuffled-record control fails, §4 | corpus |
| R16/R17 MG ECG record structure | Proven | 81 real records, §9 | corpus + noop |
| Event header, BATTERY_LEVEL payload, console text | Proven | §9 | corpus |
| **R18 byte 82 is the strap's own SpO₂ reading** | Proven | fixed 30 s / 1,200 s windows on 3 straps, firmware console text, tracks the WHOOP value, §13 | corpus + own strap + noop |
| SpO₂ accuracy against WHOOP | Measured | 0.34 % mean difference, 3 of 5 nights, §18 | own strap |
| Respiratory rate from R-R | Measured | 0.13 per min, 3 of 5 nights, §18 | own strap |
| HRV (RMSSD) | Measured | 1.48 ms, r = 0.92, 3 of 5 nights, §18 | own strap |
| Skin temperature | Measured | 0.12 °C, r = 1.00, 3 of 5 nights, §18 | own strap |
| Sleep onset | Measured | 13.8 min, 3 of 5 nights, §18 | own strap |
| R26 heart rate, on accepted bursts | Proven asleep | 1.46 bpm on 184 of 529 bursts, §16, §18 | own strap |
| R26 heart rate awake and moving | Failed | motion noise, §16 | own strap |
| R20 heart rate outside one resting session | Failed | 12–28 bpm off, §14 | corpus |
| **Wake time** | Failing | 33.6 min off, bar is 15, §18 | own strap |
| **Resting heart rate** | Failing | 3.75 bpm too low, bar is 3, §18 | own strap |
| **WHOOP's heart-rate zones: 40/60/70/80/90 % of heart rate reserve** | Proven on one account | 1379 of 1379 s on one workout, 26 of 1978 s off on another, §18 | own strap + official API |
| **Sleep need, sleep debt and nap credit rules** | Measured | exact to the millisecond on every case so far, §18 | official API |
| WHOOP's recovery, strain and sleep performance formulas | Open | §18; recovery is still in WHOOP's calibration | own strap |
| Sleep stages | Open | not attempted; the export holds per-stage minutes | |
| R21 gyro scale, R22 v9 channels, R26 sample units | Open | README D9, H5 | |

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
- **Open:** which source is red and which is infrared, and the calibration curve. A client does not need them:
  read the strap's result from byte 82 instead of deriving SpO₂ from R20.

## 6. What still needs a strap or more data

| Item | State | What closes it |
|---|---|---|
| Sleep stages | Sleep periods work (§15, §18); stages not attempted | Fit on the per-stage minutes in the WHOOP export, with R21 |
| SpO₂, HRV, respiration, skin temperature, sleep onset | Meet the bar on 3 nights (§18) | 2 more paired nights, then more wearers |
| Wake time, resting heart rate | Miss the bar (§18) | Match WHOOP's definitions |
| Scores | Inputs and scores are paired per cycle in the export (§18) | 20 cycles for recovery and sleep, 5 full-coverage cycles for strain |
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
the other 8 windows held only status codes.

**Other straps.** The same schedule holds on an MG, firmware 50.40.1.0: 402 windows over 26 nights, 401 with exactly
30 non-zero seconds, 1,199–1,200 s apart, and all but 3 of 12,059 non-zero seconds asleep (meta1971 on
[ryanbr/noop#2825](https://github.com/ryanbr/noop/pull/2825)). NOOP's code records an 8-night validation against the
app at r = +0.99. On the owner's strap the nightly value is 0.34 % from WHOOP (§18).

**The contradiction still on record.** NOOP's code notes two nights on the original #103 strap that moved opposite to the
app value. That is why NOOP ships byte 82 as an instrumentation candidate. Those two nights are unexplained, and a
statement about accuracy on every strap has to account for them.

## 14. R20 heart rate on a second session (corpus, negative)

`re/analyze_r20_hr_sessions.py`, `re/results/r20_hr_sessions.txt`. On a second R20 session (NOOP #26:
92 minutes, 36 % record coverage, awake, HR 85–89 bpm) with only 15 live-HR reference points
(converted with the time zone the log states), the R20 estimate does **not** match (MAE 12–28 bpm).
R20 heart rate therefore stays validated on one resting session only. Block configuration differs
between the sessions (block 2 drive 3400 vs 4250), and the two-channel burst does not occur in the
second one (`re/results/r20_config_bursts.txt`).

## 15. Experimental metrics: sleep periods, breathing, skin temperature, R26 heart rate (corpus, new)

`re/analyze_experimental_metrics.py`, `re/results/experimental_metrics.txt`. Four helpers in
`whoop5.experimental` / `Whoop5Experimental` (stdlib only, same inputs and outputs in both languages),
run on the captured night and cross-checked against numpy/scipy:

- **`sleep_periods`**: band state SLEEP, 300 s majority smoothing, gaps ≤ 600 s merged, ≥ 20 min kept.
  One period of 5.16 h (the capture starts already asleep, so onset = capture start; offset ~1 min after
  the last SLEEP second), 99.7 % SLEEP inside, HR mean 52.0 bpm, minimum 40 bpm (single second).
- **`respiratory_rate`**: per 60 s of R-R, a direct-DFT spectrum of the tachogram, f²-weighted, peak in
  0.1–0.5 Hz. Median **14.1 breaths/min** (IQR 12.6–15.3) over 269 windows, stable across the two halves
  of the night (14.4 / 13.8); a scipy Welch spectrum of the whole night peaks at 13.1 (bin 0.5). Synthetic
  RSA at 9 / 14 / 18 per min is recovered as 9.0 / 14.1 / 18.0. No breathing reference on this night.
- **`skin_temp_baseline`**: nightly mean **33.82 °C** (min 31.41, max 34.99, sd 0.70); deviation needs a
  second night or a given baseline.
- **`hr_from_r26`**: replaced in §16. This capture is now 15 of 17 bursts accepted, **r = 0.97, MAE 1.0 bpm**
  against R18 (46–66 bpm).

All four are experimental: one night, one wearer, no sleep-stage, breathing or thermometer reference.

## 16. R26 heart rate fails awake: cause and quality filter (own strap, new)

Five days of one owner's strap (one wearer, 286 R26 bursts with an R18 reference; `re/analyze_r26_failure.py`,
`re/results/r26_failure.txt`). The earlier r = 0.95 came from one sleeping night and did not generalise.

- **Motion is the main cause.** With the old peak-interval method, reference below 90 bpm: median error 0.8 bpm
  still, 6.4 bpm moving. Almost every burst at 90 bpm or more was also moving (39 of 40), so high heart rate
  alone is **not separated** from motion.
- **The pulse drowns.** Power at the reference heart rate against the background is about 2,000× asleep and
  about 14× awake.
- **It is not locking onto arm swing.** Wrong readings sit at the wrist-motion frequency no more often than right
  ones (20 % against 26 %). The cause is broadband motion noise, not one periodic artefact.
- **Asleep, four bursts read double** (a second dip in the pulse counted as a beat): 125 against 63 bpm.

`hr_from_r26` now takes the strongest autocorrelation peak (0 doubled readings) and returns `heart_rate_bpm` only
when the strap's `acceptance_raw` covers at least half the burst and the peak height is at least 0.3. The
filter was picked on these same bursts, so its value is untested on new data.

| | bursts | MAE | within 3 bpm |
|---|---:|---:|---:|
| old method, all | 229 | 10.0 | 46 % |
| new, unfiltered `candidate_bpm` | 234 | 19.1 | 37 % |
| **new, accepted** | **98 of 286** | **1.7** | **87 %** |
| accepted, first / second half of the data | 48 / 50 | 1.7 / 1.7 | 90 % / 84 % |
| accepted, asleep | 75 | 1.1 | 92 % |
| accepted, awake | 14 | 5.8 | 50 % |

Limits: two thirds of bursts now give no heart rate, nearly all of them awake. The few accepted awake bursts are
not reliable. Nothing above 87 bpm was accepted, so this says nothing about exercise. Awake, R18 rarely carries
R-R, so the reference there is the strap's own unconfirmed algorithm. One wearer.

### Firmware of this strap

Noop's strap logs report **50.43.1.0** up to 1 November. The first boot seen after that is 5 November 11:03, and it
logs **50.43.2.0**; the owner reads the full version as **50.43.2.0.3.30.5.0** (what the last four numbers mean is
unknown). All of §16 is on 50.43.1.0.

No frame between those points holds a boot, over 84 % of the time. The update is in one of the gaps: 1 November
11:48–23:28, 5 November 07:45–11:03, or one of two gaps under 30 minutes on 4 November. So the three nights of §18 ran
one firmware, and which one is not known. **The first night recorded after 5 November 11:03 is the first certain night on
50.43.2.0**, and it settles byte 82 on that firmware.

## 17. Re-reading trimmed history: an older acknowledgement during a burst moves trim back (own strap, new)

Firmware 50.43.2.0, one strap, `re/probe_read_pointer.py`; the official app never sends this command in our captures.

- `SET_READ_POINTER` (33) with a **u32 little-endian page** answers result 1. In the `GET_DATA_RANGE` body, the word at
  frame offset 18 becomes that page (a larger value is masked to the ring size, 0x1FFFF), and the word at offset 62
  becomes a time for that page. Write (@22), trim (@26) and capacity (@34) do not change.
- **The strap keeps a time for old pages.** Pages read back in order over about 6 days (30 Oct to 5 Nov), far behind
  trim, with about 245 pages per hour. This suggests trimmed history stays on flash, but only the time was read back,
  not a record.
- **Serving follows trim, not the pointer.** `SEND_HISTORICAL_DATA` with arguments 0 to 3 returns the pointer to trim
  and serves the same records. Moving the pointer during a transfer serves nothing new. With the pointer on an old
  page, a valid `HISTORICAL_DATA_RESULT` advances trim normally and the next chunk continues from trim.
- **An older acknowledgement during a burst moves trim back.** Outside a transfer, `HISTORICAL_DATA_RESULT` with an
  older page gets no reply and changes nothing. During a transfer, after the first HISTORY_END, the same frame sets
  trim to that page and the strap serves from there: trim went 2729 to 2629 and records from 20 minutes earlier
  arrived. Four separate spans across the ring (wrap count 6) re-read completely, at about 120x realtime, and a final
  acknowledgement put trim back to where it started. The firmware's own log shows the read-pointer payload is page
  u32 + wrap u32 ("Force Read Pointer; read page:2554 wrap count:…").

So trimmed history can be re-read while the ring still holds it (about 3 weeks at this data rate). A night can go to
the official app and still be read raw afterwards. `FORCE_TRIM` (25) was not needed and was not tried. Tried on one
strap. Steps and setup: `re/REREAD_HISTORY.md`.

**A restored trim holds.** After the restore to page 2654 at about 13:07, a range query at 14:12 still read trim 2654,
with write at 3064.

**The official app syncs on from wherever trim is.** A later run stopped at 14:44 without restoring, at records of
4 November 10:44. From 14:48 an iPhone capture shows the strap serving 44,832 records from 4 November 11:11 to 23:16, with
every acknowledgement moving forward. That this was the app is inferred: the Mac had stopped writing and lost its
encrypted link. The next two app captures run normally and end with trim equal to write, at page 3518.

So a moved trim does not stall the app; an unrestored one makes the strap serve those pages again. WHOOP did not rescore the
re-sent day: the official API shows its strain unchanged and its last update hours before the re-send. Pages that reached WHOOP
for the first time were scored even when days old, which is the case for the first sync. Whether older pages sent after that get
scored is not tested.

## 18. First comparison with the WHOOP app on the same nights (own strap, new)

Three nights synced by the official app, then re-read raw with §17: `re/validate_own_strap.py` against the WHOOP export of
the same nights (2, 4 and 5 November). One wearer, one firmware (§16). The bar is 5 nights, so the script reports these
checks as waiting until 2 more nights are paired.

| Metric | Mean difference from WHOOP | r | Against the fixed criterion |
|---|---:|---:|---|
| SpO₂ (mean of R18 byte 82 window medians) | **0.34 %** (bias +0.12) | 0.85 | meets ≤ 1.0 % |
| Respiratory rate from R-R | 0.13 per min | 0.87 | meets ≤ 1.0 |
| HRV (median 5-minute RMSSD) | 1.48 ms | 0.92 | meets r ≥ 0.7 |
| Skin temperature | 0.12 °C | 1.00 | meets r ≥ 0.7 |
| Sleep onset | median 13.8 min, later than WHOOP on all 3 nights | | meets ≤ 15 min |
| Wake time | median 33.6 min, later than WHOOP on all 3 nights (57, 34, 10) | | **misses** ≤ 15 min |
| Resting heart rate (lowest 5-minute mean) | 3.75 bpm too low, on all 3 nights | 0.39 | **misses** ≤ 3 bpm |

- **Byte scan.** Byte 82 ranked fifth at r = 0.95 and byte 71 first at r = 0.999. With about 100 bytes and three points a
  high r is expected by chance. The script's check that byte 82 ranks first runs at 5 nights.
- **The R26 filter of §16 held on data it had not seen:** on bursts after 1 November it accepted 82 of 98, MAE 0.92 bpm,
  93 % within 3 bpm, reference 52-75 bpm. Over all bursts now: 184 of 529 accepted, MAE 1.46 bpm, against 5.78 for a
  shuffled control and 19.1 unfiltered. These nights are mostly asleep, so this says nothing new about awake use.
- The R-R unit (0.996 over 166,882 records) and the R21 scale (1.003 g over 71,019 still seconds) pass on this
  strap, and all 1,066,054 frames decode.

### The export pairs inputs with scores

WHOOP's `physiological_cycles.csv` holds, per cycle: Recovery score, Day Strain, Sleep performance, resting HR, HRV, skin
temperature, SpO₂, respiratory rate, sleep need and debt, and minutes per sleep stage. So every score is available
for a whole history in one export. Nobody has to note them per day.

Two cycles now have a Day Strain and at least 80 % heart-rate coverage: TRIMP 998 for strain 12.2 and TRIMP 379 for 4.8
(`re/strain_model.py`). The strain fit needs 5, the recovery and sleep fits 20.

### Searching for the score formulas

`re/score_search.py` works from the export and raw frames only; WHOOP's servers are never contacted. Its verdicts were fixed
before any data was seen.

| Data | Result |
|---|---|
| Planted formula without noise, 8 runs each | 27-30 cycles: MODEL, about 3 points off. 45 cycles: FORMULA in 7 of 8, 0.3 off |
| Scores unrelated to the inputs | NONE, as it should be |
| Real Day Strain, one account, 336 days from a NOOP issue attachment | **MODEL**: 1.51 off on the newest 98 days, against 3.75 for guessing the mean and 3.49 for the best shuffled run. Only 2 % exact |
| The owner's export | 3 cycles: does not run |

The strain result uses daily max, mean and resting heart rate only. That 98 % of days stay inexact fits strain depending on
time in heart-rate zones, which the per-second heart rate adds (`--frames`).

### NOOP against WHOOP on the same cycles

`re/noop_compare.py` runs NOOP's real code, `main` at `2a1de760`.

Effort reads 2.4 and 3.1 below WHOOP on 2 cycles. Charge does not score yet: it needs 4 nights of baseline.

### What the official API settled

`re/whoop_api_fetch.py` saves the owner's data from WHOOP's official developer API, and `re/verify_findings.py` recomputes each claim
and fails if one stops holding (16 of 16 on the first snapshot). WHOOP's servers are used only through that official, signed-in, read-only API.

- **Sleep need** is baseline + debt + recent strain + nap credit, on all 4 sleeps.
- **Export minutes are cut off, not rounded,** for need, asleep and time in bed.
- **Sleep debt** is half the shortfall of the last main sleep, to the millisecond: 3 of 3 cases, of which one positive, one held
  across a nap and one zero. Whether carried debt adds up is not separated yet.
- **Nap credit** is exactly the nap's asleep time, on the one nap.
- **Efficiency** is asleep / in bed on 2 of 4 sleeps and 0.12 and 0.40 points higher on the other 2. Open.
- **Recovery and Sleep performance are whole numbers in the API too,** so no decimals are hidden there. Strain has decimals.
- **WHOOP flags all 3 recoveries as calibrating,** so a formula fitted on them may not hold after calibration.
- **WHOOP's heart-rate zones are heart rate reserve,** with edges at 40, 60, 70, 80 and 90 %, WHOOP's reported maximum HR and a resting HR
  of 58. From raw R18 heart rate, with no time shift, one workout matches in all 6 zones to the second (1379 of 1379 s). A second workout
  has 26 of 1978 s one zone off, all at the 60 % edge. This also shows R18 heart rate and its clock line up with what WHOOP scored. An
  earlier fit with a maximum of 214 and an 11-minute shift was wrong. `re/hrr_zones.py`.
- **Recent-strain need** grows about with strain squared on 2 cycles (power 2.05). Two points, so a lead.

### Candidate formulas

[re/SCORE_MODELS.md](re/SCORE_MODELS.md) freezes the first candidates and what is ruled out; `re/score_predictions.py` tests them on later
cycles only. None is proven. The strongest results so far are the exclusions: sleep performance is not plain asleep/need, and strain is
not one function of Edwards TRIMP.

## 19. Command request bodies from the official app (APK, new)

Each command this project had only named is built by its own class in the app (a subclass of the `xj0.b` packet base,
like `FORCE_TRIM` in §17). Reading those builders gives the exact request body, little-endian, for the command's inner
args (after `[cmd][seq]`). These are **request shapes read statically from app 5.473.0; this project has not sent any of
them to a strap.** A leading revision byte uses `REVISION_1..4` = 1..4.

| Command | Body (little-endian) |
|---|---|
| `RUN_HAPTICS_PATTERN` (79) | `patternId u8, numberOfLoops u8, 00, 00, 00` (5 B). Matches NOOP's observed `02 03 00 00 00` = preset 2, 3 loops |
| `RUN_ALARM` (68) | `revision u8` alone, or `revision u8, strapAlarmId u8` |
| `DISABLE_ALARM` (69) | `revision u8, alarmId u8` (alarmId `0xFF` = all), or `revision u8` alone |
| `GET_ALARM_TIME` (67) | `revision u8, alarmId u8`, or `revision u8` alone |
| `SET_ALARM_TIME` (66) rev 1 | `01, alarmTime u32, field u16` (7 B) |
| `SET_ALARM_TIME` (66) rev 4 | `04, strapAlarmId u8, alarmTime u32, field u16, AlarmHapticsPattern` (~21 B) |
| `SELECT_WRIST` (123) | `01, input u8` (wrist selection) |
| `ENABLE_OPTICAL_DATA` (107) | `01, on u8` (0 or 1) |
| `TOGGLE_OPTICAL_MODE` (108) | `01, on u8` (0 or 1) |
| `GET_BATTERY_PACK_INFO` (151), `STOP_RAW_DATA` (82) | no args (shared empty-body helper) |

`AlarmHapticsPattern` (12 B): `waveformEffect1..8 u8` (eight bytes), `loopControlForEffects u16`,
`overallWaveformLoopControl u8`, `alarmDurationInSeconds u8`.

`alarmTime` is a u32 (the app truncates a long to 32 bits); the `field u16` next to it is the time's second component,
likely a timezone or local-minute offset — **inferred, not confirmed**. This closes most of README item H7 (alarm and
haptic bodies) from the app side; LED/TIA-config bodies and the on-strap responses to these commands are still open, and
nothing here has been exercised on a strap.

## 20. Sources

- Official WHOOP Android app 5.473.0 (static analysis for interoperability; nothing reproduced).
- [ryanbr/noop](https://github.com/ryanbr/noop) protocol docs, test vectors and the #1992 corpus
  donated by @p3LZ3r.
- [b-nnett/goose](https://github.com/b-nnett/goose) (archived).
- [OpenStrap/protocol](https://github.com/OpenStrap/protocol).
- [Johga/Gadgetbridgefork](https://codeberg.org/Johga/Gadgetbridgefork/src/branch/whoop).
- [Gadgetbridge #5731](https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/5731) (tazjin).
- [johnmiddleton12/wearable](https://github.com/johnmiddleton12/wearable), the WHOOP 4.0 counterpart
  this repository is modelled on.

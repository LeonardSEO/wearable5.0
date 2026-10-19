# WHOOP 5.0 / MG BLE protocol — findings

_Last updated 2026-10-19._ Independent interoperability research; not affiliated with WHOOP, Inc.
Every claim carries an evidence tier (defined in `protocol/whoop5_protocol.json`):
**corpus** (verified here on real 5/MG frames), **apk** (static analysis of the official Android app
5.473.0, facts only), **noop / goose / johga** (community sources), **constructed** (arithmetic only).

This repository did **not** have a WHOOP 5.0 strap. Everything marked *corpus* was verified on
frames other owners published: the v20 corpus and paired ground truth from
[ryanbr/noop#1992](https://github.com/ryanbr/noop/issues/1992), and the real R18 / R26 / metadata
frames that NOOP publishes as test vectors.

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
| Live HR + R-R (packet 40) | ✅ | noop |
| R18 biometric summary: HR, R-R, gravity, steps, skin temp, band state | ✅ structure; field meanings partly provisional | corpus (3 frames) + noop + johga |
| R20 optical: which channels carry the pulse | ✅ **new** — see §4 | corpus |
| R20 optical → heart rate that tracks a varying reference | ✅ **new**, r ≈ 0.8, MAE ≈ 2 bpm | corpus |
| R21 six-axis IMU, R26 compact optical, R22 v9 | ✅ structure | noop |
| SpO₂ | ⚫ not a value on the wire; candidate measurement burst located (§5) | corpus (thin) |
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

- No SpO₂ value exists in any documented record, and the app computes none (§3).
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
| Sleep detection / stages | Need overnight R21 motion + R18 band state + R-R | One or more donated nights (R18 + R21) with a sleep reference (watch or WHOOP export) |
| Skin temperature consistency | R18 `u16@73 / 100 °C` agrees across NOOP, Johga and goose; firmware coverage unknown | R18 from more firmware versions |
| SpO₂ | §5 | Overnight bursts + exported SpO₂ |
| Overnight HRV / respiration | R18 carries ≤ 4 R-R words per record | R20 beat timing (§4) is a candidate dense source; validate against R-R |
| Bonding refusals on some Android phones | Strap refuses SMP pairing (NOOP #1635) | Hardware investigation |

## 7. Sources

- Official WHOOP Android app 5.473.0 (static analysis for interoperability; nothing reproduced).
- [ryanbr/noop](https://github.com/ryanbr/noop) protocol docs, test vectors and the #1992 corpus
  donated by @p3LZ3r.
- [b-nnett/goose](https://github.com/b-nnett/goose) (archived).
- [OpenStrap/protocol](https://github.com/OpenStrap/protocol).
- [Johga/Gadgetbridgefork](https://codeberg.org/Johga/Gadgetbridgefork/src/branch/whoop).
- [Gadgetbridge #5731](https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/5731) (tazjin).
- [johnmiddleton12/wearable](https://github.com/johnmiddleton12/wearable), the WHOOP 4.0 counterpart
  this repository is modelled on.

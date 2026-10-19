<h1 align="center">wearable5.0</h1>

<p align="center">
  <b>An open, tested protocol library for the WHOOP&nbsp;5.0&nbsp;/&nbsp;MG band.</b><br>
  Read your own biometrics from your own strap over Bluetooth LE: no account, no cloud.
</p>

<p align="center">
  <img alt="Device" src="https://img.shields.io/badge/device-WHOOP%205.0%20%2F%20MG-222">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B%20%C2%B7%20stdlib%20only-3776AB">
  <img alt="Swift" src="https://img.shields.io/badge/swift-5.9%2B%20%C2%B7%20no%20CoreBluetooth-F05138">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-research%20preview-orange">
</p>

---

`wearable5.0` is the WHOOP 5.0 / MG counterpart of
[johnmiddleton12/wearable](https://github.com/johnmiddleton12/wearable) (WHOOP 4.0). It gives client
apps such as [NOOP](https://github.com/ryanbr/noop) one canonical, versioned description of the 5/MG
wire protocol, plus matching decoders in Python and Swift that are tested against each other and
against frames captured from real straps.

> [!IMPORTANT]
> Independent interoperability research. **Not affiliated with WHOOP, Inc.** Not a medical device.
> This library parses and builds bytes; it never connects to a device by itself. See
> [DISCLAIMER.md](DISCLAIMER.md).

## Contents

- [Features](#features)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Verification status](#verification-status)
- [Open items: what still needs a WHOOP 5.0](#open-items-what-still-needs-a-whoop-50)
- [How it compares](#how-it-compares)
- [Using it from NOOP](#using-it-from-noop)
- [Contributing data](#contributing-data)
- [Credits](#credits)

## Features

| | |
|---|---|
| **Canonical schema** | [`protocol/whoop5_protocol.json`](protocol/whoop5_protocol.json): GATT, envelope, 87 commands (82 from the current official app plus 5 firmware-only ones documented by NOOP), 58 events, 16 packet types, response bodies and record layouts. Every entry is tagged with where the fact comes from. |
| **Byte-exact framing** | CRC16-Modbus header, CRC32 body, 4-byte padding, BLE fragment reassembly. Reproduces the strap's CLIENT_HELLO and history ACK byte for byte. |
| **Record decoders** | Live HR + R-R (packet 40), R18 biometric summary, R20 optical blocks, R21 six-axis IMU, R22 v9 channels, R26 compact optical, IMU streams 51/52, events, history metadata. Unknown layouts are preserved raw, never dropped. |
| **Sync support** | Field-exact `GET_DATA_RANGE` (page backlog and newest-page clock) and the `HISTORICAL_DATA_RESULT` ACK built from the verbatim HISTORY_END token. |
| **Safety list** | The commands that can brick, wipe or lock a strap are flagged `destructive` in the schema and exposed in both languages. |
| **Two languages, one truth** | Python (stdlib only) and a Swift package. Parity is enforced by golden vectors in CI. |
| **New research** | Heart rate recovered from raw R20 optical data, validated against a varying reference ([FINDINGS §4](FINDINGS.md#4-r20-optical-the-pulse-channels-corpus-new)). |

## Repository layout

```
protocol/                 whoop5_protocol.json: the single source of truth (edit only this)
python/whoop5/            reference decoder (framing, decode, synthetic frames)
python/tests/             unit tests, including real frames from 5/MG straps
Packages/Whoop5Protocol/  Swift package + whoop5-decode CLI
fixtures/golden.json      cross-language parity vectors (generated)
re/                       reverse-engineering analyses and their results
scripts/sync-schema.sh    copies the schema to every consumer and regenerates vectors
FINDINGS.md               the protocol write-up and evidence
```

## Getting started

**Python**

```bash
cd python && python3 -m unittest discover -s tests
```

```python
from whoop5 import Reassembler, decode_frame, history_ack

r = Reassembler()
for notification in notifications:              # bytes from fd4b0003 / fd4b0004 / fd4b0005
    for frame in r.feed(notification):
        packet = decode_frame(frame)
        if packet.get("meta_name") == "HISTORY_END":
            ack = history_ack(bytes.fromhex(packet["end_token_hex"]))   # send only after you persisted the chunk
```

**Swift** (add `Packages/Whoop5Protocol` as a local or remote package)

```swift
import Whoop5Protocol

var reassembler = Whoop5Reassembler()
for frame in reassembler.feed(notificationBytes) {
    switch try Whoop5Decoder.decode(frame) {
    case .record(_, .biometric(let r18)):  print(r18.heartRate, r18.rrMs, r18.skinTempC ?? .nan)
    case .commandResponse(let c):          print(c.commandName, c.dataRange?.pagesBehind ?? 0)
    default:                               break
    }
}
```

```bash
cd Packages/Whoop5Protocol
swift test                                                # requires Xcode (XCTest)
swift run whoop5-decode --parity ../../fixtures/golden.json   # works with Command Line Tools only
swift run whoop5-decode aa0108000001e67123019101363e5c8d
```

**Changing the protocol:** edit `protocol/whoop5_protocol.json`, run `scripts/sync-schema.sh`,
then run both test suites. CI fails if the copies drift.

## Verification status

Every fact carries one of these evidence levels (defined in the schema):

| Level | Meaning |
|---|---|
| **corpus** | Verified in this repository on frames captured from real 5/MG straps. |
| **apk** | Read from static analysis of the official Android app (5.473.0), facts only. |
| **community** | Documented by NOOP, goose, OpenStrap or Johga; partly hardware-confirmed by them. |
| **constructed** | An arithmetic or structural rule with no physical validation. |

| Area | Level |
|---|---|
| Envelope, CRCs, padding, reassembly | corpus |
| CLIENT_HELLO, HISTORY_END token, history ACK | corpus |
| Command / event / packet-type numbers, destructive set, device families | apk |
| GET_DATA_RANGE cursor fields (write, trim, capacity) | apk + community |
| R18 heart rate, R-R, steps, skin temperature, band state | corpus (3 frames) + community |
| R20 block layout and which channels carry the pulse | corpus |
| R21, R22, R26, packets 51/52 | community |

## Open items: what still needs a WHOOP 5.0

**Short answer: yes.** The library is complete for framing, history sync and record *structure*.
Several *meanings*, scales and behaviours have only been inferred, or confirmed on one strap, one
firmware or a 17-minute window. Each item below needs either a strap in hand or captures donated by
owners. None of them blocks using the library; they limit how far a client should trust a field.

### Needs a strap (live interaction)

| # | Item | Current state | How to verify |
|---|---|---|---|
| H1 | Full connect → bond → hello → sync session on iOS, macOS and Android | Built from verified frames, never run end-to-end by this project | Pair a 5.0 and run a complete offload through a client using this library |
| H2 | Bonding refusals on some Android phones | Strap refuses SMP pairing in an HCI capture (NOOP #1635); cause open | Controlled pairing attempts with HCI logging |
| H3 | `GET_DATA_RANGE` newest-page clock (body offset 57) | Documented by NOOP; no captured reply in this repo | Capture one SUCCESS reply and compare with the newest offloaded record |
| H4 | HISTORY_END token second word (write-wrap state) | Echoed verbatim, meaning inferred | Offload across a ring wrap |
| H5 | R21 IMU scale (4096 LSB/g, ±2000 °/s) and 100 Hz rate | Candidate only | Strap flat on a table (‖a‖ = 1 g) plus one timed 360° rotation |
| H6 | Dedicated IMU stream packets 51/52 | Layout documented, never observed | Enable IMU streaming and capture |
| H7 | Command bodies for alarms, haptics, LED/TIA config | Numbers known, payloads not in the schema | Capture the official app setting each one |
| H8 | Format-2 envelope | Exists, negotiation unknown | Observe a session that switches format |

### Needs more data (a strap, or donated captures)

| # | Item | Current state | Data that settles it |
|---|---|---|---|
| D1 | R20 LED wavelengths (which source is green, red, infrared) | Source codes 1–4 seen; identity unknown | Captures across a toggle of the `ir_hw_switching` feature flag, or with a known light source |
| D2 | SpO₂ | No value on the wire; a 21-second two-channel burst found once (FINDINGS §5) | Overnight captures with several bursts plus the owner's WHOOP SpO₂ export for the same nights |
| D3 | Sleep detection and stages | R18 band state + R21 motion decoded; no staging model validated | Overnight R18 + R21 with a sleep reference (watch stages or WHOOP export) |
| D4 | HR from R20 optical | r ≈ 0.8, ~2 bpm on one wearer, one evening, resting | Multiple wearers, motion, overnight |
| D5 | Dense overnight HRV from R20 beat timing | Not attempted | R20 overnight plus simultaneous R-R |
| D6 | Respiratory rate | No field identified | Overnight data plus the WHOOP export |
| D7 | Skin temperature (R18 `u16@73 / 100 °C`) across firmware | Agrees across three sources, coverage 50.38–50.42 | R18 from other firmware versions, with the WHOOP export |
| D8 | R18 provisional fields (alt HR validity, bytes 75–82, optical bytes 106–109, f32 @113) | Raw, meaning open | Correlation against a WHOOP export over many nights |
| D9 | R22 v9 channel meaning and R26 sample units | Structure only | Captures with the related feature flags toggled |
| D10 | Event payloads (e.g. `TEMPERATURE_LEVEL`, `STRAP_CONDITION_REPORT`) | Event numbers known, payloads opaque | Captures of each event |

### Needs a developer machine

| # | Item | How to verify |
|---|---|---|
| T1 | Swift XCTest suite | Runs in CI on macOS; the parity CLI already passes locally |

## How it compares

Checked on 2026-10-19 against the source of each project. Goose and NOOP are full apps; this
repository is a protocol library, so the comparison covers the protocol layer only.

| | wearable5.0 | [goose](https://github.com/b-nnett/goose) (archived) | [NOOP](https://github.com/ryanbr/noop) 5/MG path |
|---|---|---|---|
| Format-1 framing, CRCs, reassembly | ✅ strict (rejects bad CRC) | ✅ lenient (keeps truncated / bad-CRC frames with warnings) | ✅ |
| Command table | 87, with source per entry | 75, with risk gates | 80 |
| Commands 146–147, 155–159 (new clock pair, certificates, `LOCK_DEVICE`) | ✅ | — | — |
| Event table | 58 | 33 | 58 |
| HISTORY_END token and ACK | ✅ | ✅ | ✅ |
| GET_DATA_RANGE backlog in pages | ✅ | ✅ | ✅ (diagnostic only) |
| GET_DATA_RANGE newest-page clock (field-exact) | ✅ | — | — (timestamp scan, not fed to 5/MG sync) |
| R18 fields (HR, R-R, gravity, steps, skin temp, band state) | ✅ | header + HR byte | ✅ |
| R20 optical blocks, all ten channels | ✅ | — | ✅ |
| R21 IMU arrays, R26 delta reconstruction, R22 v9 | ✅ | summaries | ✅ |
| Which R20 channels carry the pulse; HR from R20 | ✅ validated with a control | — | — |
| Device-family table incl. battery-pack service | ✅ | partial | `1150…` listed as unsupported |
| Machine-readable schema with evidence per fact | ✅ | — | ✅ (no per-fact source) |
| Python + Swift with enforced parity | ✅ | Rust + Swift | Swift + Kotlin |
| BLE client, storage, scoring algorithms, UI | — (out of scope) | ✅ | ✅ |

Most protocol offsets here were first documented by NOOP and goose; this repository consolidates
them, adds the current app's tables, and contributes the R20 heart-rate finding. Other community
decoders exist, for example [whoop-local](https://github.com/a9eelsh/whoop-local) (single-file
Python, derives HRV from R26).

## Using it from NOOP

NOOP's WHOOP 5/MG path is currently derived from goose, which is archived. This library offers
drop-in improvements, each small enough to land on its own:

1. **Feed sync from the 5/MG data range.** NOOP already logs the page backlog; the field-exact
   newest-page clock (`DataRange.newestUnix`) can fill `strapNewestTs`, which is nil on 5/MG today
   and drives the auto-continue storm in [ryanbr/noop#1992](https://github.com/ryanbr/noop/issues/1992).
   Verify with H3 first.
2. **Bank heart rate from R20 records** that are rejected today, which keeps the iOS history
   frontier open (also #1992). Ship as instrumentation until D4 is done.
3. **Allow-list against the current app's command table**, including the destructive set and
   commands 146–147 and 155–159, which NOOP's table does not list yet.

## Contributing data

The open items above are mostly a data problem. If you own a 5.0 or MG:

- Share **frames, not HCI logs**: CRC-valid frame hex as NOOP's RawHistoryArchive writes it. HCI logs
  can contain your MAC address, serial number and identity blocks.
- Overnight offloads with a reference (watch sleep stages, or the WHOOP data export for the same
  nights) are the most valuable.
- See [re/README.md](re/README.md) for the analysis workflow.

## Credits

This work stands on the community's protocol research. With thanks to:

- [ryanbr/noop](https://github.com/ryanbr/noop) and its contributors, for the most complete public 5/MG
  documentation and test vectors; and to @p3LZ3r for the v20 corpus and ground truth in #1992.
- [b-nnett/goose](https://github.com/b-nnett/goose), the first public 5.0 BLE client.
- [OpenStrap/protocol](https://github.com/OpenStrap/protocol) and
  [Johga's Gadgetbridge branch](https://codeberg.org/Johga/Gadgetbridgefork/src/branch/whoop).
- tazjin, [Gadgetbridge #5731](https://codeberg.org/Freeyourgadget/Gadgetbridge/issues/5731).
- [johnmiddleton12/wearable](https://github.com/johnmiddleton12/wearable), whose WHOOP 4.0 method this
  repository follows.

Released under the [MIT License](LICENSE).

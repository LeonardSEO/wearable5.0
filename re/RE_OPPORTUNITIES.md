# What is left to reverse-engineer, and what it would add

A working list, ranked, for the WHOOP 5.0 / MG now that this project has the strap, a Mac BLE client, an HCI
capture of the official app, and a static decompilation of the Android app (5.473.0, kept out of the repo). Each
entry says what is already known, what evidence would settle it, and what it would add to a client like this one.

**Scope and safety.** Everything here is for interoperating with a strap you own. Two lines this project does not
cross: it never redistributes WHOOP code, firmware or assets, and it never writes firmware to a strap. The
firmware subsystem below is documented as a protocol so a client can *know about* an update; flashing is left to
the official app, because the on-strap write commands are destructive and can brick the device.

## 1. Firmware update protocol (app side mapped; strap side intentionally not automated)

The Android app's `OtaFirmwareUpdateApi` talks to `https://api.prod.whoop.com`:

| Step | Endpoint (POST) | Request | Response |
|---|---|---|---|
| Check | `firmware-service/v4/firmware/check?deviceName=` | `List<ChipFirmwareVersion>` = {chipName, version} per chip | `DesiredDeviceFirmwareConfig` {hardwareDevice, isForceUpdate, forceUpdateRepromptTime, chipFirmwares[]} |
| Fetch | `firmware-service/v4/firmware/version?deviceName=` | `DownloadFwFilePayload` {currentChipFirmwares[], chipFirmwareUpgrade[]} | `DesiredDeviceFirmwareUpdate` {desiredDeviceFirmwareConfig, firmwareFile} |
| Report | `firmware-service/v4/firmware/result?deviceName=` | `ReportFwUpdateResultPayload` + header `X-WHOOP-Auxiliary…` | — |
| Unlock | `firmware-service/v4/strap/unlock-token` | header `X-WHOOP-Strap-Id`, `StrapUnlockRequest` | `StrapUnlockResponse` |
| Events | `firmware-service/v1/events` | strap firmware events | — |

Observations (static, from the decompiled app): the version check is per chip, driven by the versions the strap
reports; the server decides the target and can force it (`isForceUpdate`). `firmwareFile` is a single string on the
fetch response, with no sibling URL or checksum field, so the firmware image appears to come back inline from the
authenticated API rather than from a public CDN. Update strategies are `DefaultUpdateStrategy`, `DfuUpdateStrategy`
(`ENTER_BLE_DFU`, 45) and `BatteryPackUpdateStrategy`, driven by `FirmwareUpdateWorker`. The strap-side load path is
`START_FIRMWARE_LOAD` (36/142) → `LOAD_FIRMWARE_DATA` (37/143) → `PROCESS_FIRMWARE_IMAGE` (38/144) →
`VERIFY_FIRMWARE_IMAGE` (83); all are `destructive` in `protocol/whoop5_protocol.json`.

- **Would add:** a client could report the current chip versions and read back whether a newer firmware exists and
  whether it is forced, without the official app — read-only, no write path.
- **Settles it:** an HCI capture of the official app running an actual update, to confirm the request bodies, the
  `firmwareFile` encoding and the on-strap verify/commit handshake. Not yet captured.
- **Not planned here:** sending the load/verify commands. Document them; do not drive them.

## 2. More of the command surface, from the app

The app names commands this project has not exercised. Highest-value, lowest-risk first; the destructive ones are
documented only.

- **`GET_BODY_LOCATION_AND_STATUS` (84)** — read-only; would confirm on-wrist / body-location state cleanly.
- **`GET_EXTENDED_BATTERY_INFO` (98), `GET_BATTERY_PACK_INFO` (151)** — battery health beyond the SoC/mV we decode.
- **Alarm/haptics bodies** — `SET_ALARM_TIME` (66), `GET_ALARM_TIME` (67), `RUN_ALARM` (68), `RUN_HAPTICS_PATTERN`
  (79), `GET_ALL_HAPTICS_PATTERN` (80): the app builds these payloads; capturing it setting an alarm would fill
  README item H7 (alarm/haptic/LED bodies).
- **Optical / raw-data toggles** — `ENABLE_OPTICAL_DATA` (107), `TOGGLE_OPTICAL_MODE` (108), `START_RAW_DATA` (81),
  `STOP_RAW_DATA` (82): the hooks behind R20/R26. See §4 for the on-demand idea.
- **`SELECT_WRIST` (123), advertising name get/set (141/140)** — small, read-mostly configuration.
- **Feature-flag / device-config reads** — `GET_FF_VALUE` (128), `GET_DEVICE_CONFIG_VALUE` (121): read back what the
  app set, to confirm FINDINGS §10 against this firmware.

## 3. The app itself

- **Score model inputs.** How the app turns R18/R20/R26 into recovery, strain and sleep. Static analysis can show
  which decoded fields feed which score, which is what a client needs to reproduce them.
- **The API surface.** `api.prod.whoop.com` and `app-cdn.prod.whoop.com` — the sync/upload endpoints and payloads.
  An HCI or TLS-aware capture of a login + sync would map these. Credentials and personal data stay out.
- **What the app uploads.** `firmware-service/v1/events` and the raw-data uploaders show the app ships strap events
  and raw frames to WHOOP; worth knowing what leaves the device.

## 4. Gaps worth closing (what is missing or weak today)

- **On-demand SpO₂ / optical measurement.** Today SpO₂ (byte 82) only appears in the strap's own ~20-minute sleep
  windows. The strap has optical-enable commands (107/108/81), so a *candidate* is to drive an optical capture
  awake and derive SpO₂ or HR on demand. **Unverified**: the app strings for "on_demand" / "manual measurement"
  relate to Health-Connect manual entry, not an on-strap trigger, so whether these commands yield a valid SpO₂
  awake is an open experiment — and §16 already shows optical HR fails with motion.
- **Resting HR and wake time** miss the WHOOP app (§18). Our definitions differ from theirs; worth matching the
  app's method.
- **Byte 82 is not yet the top-correlating byte** over 3 nights (§18). Needs ≥5 nights, which the re-read method
  now makes practical.
- **Gyro scale** (R21) is still open; accel is confirmed (§18). One timed rotation with gyro on would settle it.
- **R22 v9 channels and R26 sample units** (README D9) remain structure-only.

## Evidence

APK class/endpoint names and command list: static analysis of `com.whoop.android` 5.473.0 (decompiled, not in the
repo). The five `firmware-service/v4` endpoints, the request/response model fields and the on-strap command names are
byte-for-byte identical in 5.475.0 (strings of its `classes*.dex`), so this holds for both app versions. On-strap command numbers and destructive set: `protocol/whoop5_protocol.json`. Night comparisons: §18.

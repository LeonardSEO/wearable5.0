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

**Flow detail (static, from the decompiled 5.473.0 app).** A WorkManager job (`PeriodicFwUpdateCheckWorker`) runs the
check on a schedule. `firmwareFile` on the fetch response is **Base64**: the app decodes it to bytes in-process
(`og1/a.java`: `byte[] b = base64.b(update.getFirmwareFile(), …)`), writes it to a per-serial file
(`firmwareFilesHelper.i(serial, "boylston", …)`, "boylston" being a chip codename), and only then transfers it to the
strap. Two transfer paths: the main sensor chip over the WHOOP command path (36/37/38/83), and the battery pack / nRF
chip over **standard Nordic DFU** (`no.nordicsemi.android.dfu.DfuBaseService`, `ENTER_BLE_DFU` 45, `DfuUpdateStrategy`).
So the image is server-signed and comes inline from the authenticated API, not from a public CDN; there is no
plaintext URL to fetch and no separate checksum field in the model.

- **Would add:** a client could report the current chip versions and read back whether a newer firmware exists and
  whether it is forced, without the official app — read-only, no write path.
- **Settles it:** the check/fetch itself is HTTPS to `api.prod.whoop.com`, not BLE, so the BLE logger cannot see it and
  a proxy would meet certificate pinning; the request/response **shapes** are already known from the app (above). The
  BLE logger does capture the on-strap transfer, but only while a real update runs — WHOOP decides when.
- **Not planned here:** sending the load/verify commands or decoding a firmware image. Document the flow; do not drive
  it or redistribute any image.

## 2. More of the command surface, from the app

The app names commands this project has not exercised. Highest-value, lowest-risk first; the destructive ones are
documented only.

- **`GET_BODY_LOCATION_AND_STATUS` (84), `GET_EXTENDED_BATTERY_INFO` (98), feature-flag/config reads (128/121)** —
  their builder classes were not located in a quick pass (likely a shared empty-body sender); the response layouts
  are the open part. Still worth a capture.
- **`GET_EXTENDED_BATTERY_INFO` (98), `GET_BATTERY_PACK_INFO` (151)** — battery health beyond the SoC/mV we decode.
- **Alarm/haptics bodies — DONE from the app (§19).** Request bodies for 66/67/68/69/79, `SELECT_WRIST` (123),
  `ENABLE_OPTICAL_DATA` (107) and `TOGGLE_OPTICAL_MODE` (108) are decoded and in `protocol/whoop5_protocol.json`
  (`request_bodies`). Still open: `GET_ALL_HAPTICS_PATTERN` (80), LED/TIA bodies, and the on-strap *responses*.
- **Optical / raw-data toggles** — `ENABLE_OPTICAL_DATA` (107), `TOGGLE_OPTICAL_MODE` (108), `START_RAW_DATA` (81),
  `STOP_RAW_DATA` (82): the hooks behind R20/R26. See §4 for the on-demand idea.
- **`SELECT_WRIST` (123), advertising name get/set (141/140)** — small, read-mostly configuration.
- **Feature-flag / device-config reads** — `GET_FF_VALUE` (128), `GET_DEVICE_CONFIG_VALUE` (121): read back what the
  app set, to confirm FINDINGS §10 against this firmware.

## 3. The app itself

- **Score model inputs — settled: the scores are not in the app.** Recovery, strain and sleep are computed
  server-side, not on the device. The decompiled app has no HRV/strain/recovery formula (no Kubios/RMSSD/TRIMP
  constants, no calculator or engine class); the `recovery`, `strain` and `sleep` values arrive as deserialized DTO
  fields and every score path is a fetch or a leaderboard read (`community-service/.../recovery/score`, etc.). So a
  client **cannot** extract WHOOP's scoring model from the app — it would have to reproduce it from the raw inputs
  itself, which is exactly what this project's experimental metrics do. The useful half is the input list below.
  **Empirical route (`re/score_model.py`):** your export pairs each cycle's inputs (HRV, resting HR, respiratory rate,
  sleep) with the score WHOOP gave it, and those pairs are yours. The script fits a model per score on your history and
  reports how well it reproduces WHOOP, so a client can show the same numbers from the inputs this library decodes.
  Caveats: recovery/strain are baseline-relative, so a fit reproduces *your* account's mapping, not a universal
  formula; it needs the full export (>= 20 cycles), not one week; strain also needs per-second day HR (re-read frames)
  for time-in-zone. First run on a 3-cycle export only showed sleep performance is **not** the naive asleep/need ratio
  (33 % off on 3 nights) — worth settling on a full history. First 3 cycles, preliminary: WHOOP sleep performance looks
  capped near 95 % and curved (ratio 89/181/69 % mapped to 90/95/81 %), and recovery did **not** track absolute HRV/RHR
  (its best HRV + lowest RHR night scored lowest), consistent with baseline-relative normalization. The account is ~2
  weeks old, so there are only 3 scored cycles yet; the fit needs a few more weeks of wear.
- **What the strap uploads (the raw inputs to the server model).** The app ships, over `api.prod.whoop.com`:
  raw frames (`research-metrics-service/v1/{raw,imu,optical}/upload`, `com.whoop.dataSyncService.rawdata`
  `RawDataUploadWorker`), sensor metrics (`metrics-service/v1/metrics/sensor`), strap and firmware events
  (`firmware-service/v1/events`, `hardware-observability-service/v1/events/relative`), console logs
  (`NewConsolePacketUploader`) and GPS. In other words the server gets the same R18/R20/R21/R26 streams and events this
  library already decodes, and derives the scores from them; nothing extra is measured on the phone.
- **The API surface.** `api.prod.whoop.com` and `app-cdn.prod.whoop.com`, a large set of `*-service/vN/` REST
  endpoints (firmware, metrics, research-metrics, coaching, community, health, …). Mapping the request/response bodies
  needs a TLS-aware capture of a login + sync and will meet certificate pinning; the endpoint paths are already
  readable statically. Credentials and personal data stay out of the repo.

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

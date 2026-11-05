# Re-reading trimmed history from your own WHOOP 5.0 / MG

A strap gives each record to whichever client acknowledges it first. That used to force a choice for every night:
the official app (WHOOP's scores and export) or a raw client (the frames). This method gets both from the same night,
because the strap keeps trimmed pages on flash until the ring overwrites them: about 3 weeks at the normal rate of 245 pages an
hour, and far less after raw capture, which writes about 3600 pages an hour.

**Status:** works on one strap, firmware 50.43.2.0: four spans of 6 to 8 hours, all complete, with trim restored
afterwards. The official app synced on normally after a later run that left trim moved (FINDINGS §17). Other firmware is untested.

**This moves the strap's history bookkeeping. It is not used by the official app. Use it only on a strap you own, and
accept that an untested firmware may behave differently.** Never send `FORCE_TRIM` (25) for this: it is not needed.

## How it works

| Fact | Evidence |
|---|---|
| The firmware keeps read, write, oldest and trim pointers | console: `Flash: no unread data, read ptr 2654, write ptr 2654, oldest ptr 2688, trim ptr 2653.` |
| A position is a page plus a ring pass (wrap count) | console: `Force Read Pointer; read page:2554 wrap count:…`; pages above the write head are one wrap older |
| `SET_READ_POINTER` (33) moves the read pointer and exposes that page's stored time | `GET_DATA_RANGE`: pointer u32 at frame offset 18, its time u32 at offset 62 |
| Starting a transfer resets the read pointer to trim, so 33 alone re-reads nothing | arguments 0-3 of command 22 tested, with and without the correct wrap |
| An older `HISTORICAL_DATA_RESULT` (23) outside a transfer does nothing | no reply, trim unchanged |
| **The same frame during a transfer sets trim, and the strap serves from there** | trim 2729 to 2629, records from 20 minutes earlier arrived |

So one re-read is:

1. Quit every other client of the strap: the strap serves one central and holds one bond.
2. `GET_DATA_RANGE` for write, trim and capacity. Note trim and its wrap if you want to restore them.
3. Find the start page: command 33 with `page u32 + wrap u32`, then read the stored time back; binary search by distance
   behind the write head. Pages above the head use `wrap - 1`.
4. `SEND_HISTORICAL_DATA` (22), `00`. Wait for the first HISTORY_END.
5. `HISTORICAL_DATA_RESULT` (23), `01 + page u32 + wrap u32` with the start page. Trim moves there.
6. Store each chunk, then acknowledge its own HISTORY_END token as usual, until the records pass your end time.
7. Send 23 once more with the trim from step 2, then `ABORT_HISTORICAL_TRANSMITS` (20). The official app continues from
   there and misses nothing.

Rate: about 120x realtime, so a night takes 3 to 4 minutes.

## Running it on a Mac

macOS kills a process that opens Bluetooth without declaring it, so the client runs inside a small app bundle:

```bash
re/build_probe_app.sh ~/whoop-tools/WhoopProbe.app .venv/bin/python
```

Then free the strap and pair it to the Mac:

1. iPhone: swipe the WHOOP app away and turn Bluetooth off in Settings.
2. Mac: forget the strap in System Settings, Bluetooth.
3. If the connection still fails with `Peer removed pairing information`, run `sudo pkill bluetoothd`.
4. Tap the strap repeatedly until it flashes blue, then run the client straight away.

Run through `open`, because the app is what macOS gives Bluetooth permission to:

```bash
open -W --stdout run.log --stderr run.log --env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  ~/whoop-tools/WhoopProbe.app --args "$PWD/re/probe_read_pointer.py" fetch \
  --span "2026-11-03 23:20" "2026-11-04 07:20" --restore 2654:7 --out my-data
```

`--restore PAGE:WRAP` belongs on the last span only. Take trim and wrap from the `range:` line of your first run
(`probe_read_pointer.py range`), and read `run.log` for the result. Frames go to `my-data/frames.jsonl`, which
`validate_own_strap.py` reads along with your WHOOP export.

Pairing the Mac takes the bond from the phone, so re-pair in the WHOOP app afterwards. Because the ring keeps about 3
weeks, you can sleep and sync normally and do this once for a whole batch of nights.

## Sending older nights to the official app

Under test. Nights that went to another client never reached WHOOP. Moving trim back and leaving it there makes the strap
serve them to the app, along with everything after them. Whether WHOOP scores them is the open question, and it touches the
owner's real account, so go one night at a time. Save the current state first, with `re/whoop_api_fetch.py` or an export.

```bash
open -W --stdout run.log --stderr run.log --env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  ~/whoop-tools/WhoopProbe.app --args "$PWD/re/probe_read_pointer.py" backfill --start "2026-10-31 22:00" --out my-data
```

That only reports the page. Add `--apply` to move trim, and `--undo PAGE:WRAP` to put it back before the app syncs.

## Costs seen so far

- The phone loses its bond each time the Mac pairs.
- An acknowledgement moves trim. A re-read now resumes after a dropped link. With trim moved forward past unsynced pages, the official app misses them, so restore it.
- Reads without `--restore` leave trim at the end of the span. With a span in the past, the strap serves everything after
  it to the app again. WHOOP did not rescore the re-sent day (FINDINGS §17).

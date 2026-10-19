# Disclaimer

**Independent and unofficial.** This project is not affiliated with, endorsed by, or sponsored by
WHOOP, Inc. "WHOOP" is a trademark of its owner and is used only to identify the hardware this
software interoperates with.

**Not a medical device.** Nothing here is clinically validated or medical advice.

**No proprietary material.** This repository contains only original code and factual protocol
observations. Some facts (command, event and packet numbers; the GET_DATA_RANGE field roles) were
confirmed by static analysis of the official Android app, solely for interoperability with a device
the user owns (cf. 17 U.S.C. §1201(f) and EU Directive 2009/24/EC art. 6). No WHOOP code, firmware,
app binaries, decompiled source, assets or credentials are included, linked or redistributed. The
decompiled app and any captures stay outside this repository (see `.gitignore`).

**Your device, your data, your risk.** The library builds and parses bytes; it does not connect to
anything. Never send the commands listed as `destructive` in the schema.

Good-faith takedown or correction requests: open an issue.

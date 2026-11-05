#!/bin/sh
# Build the macOS app bundle that lets probe_read_pointer.py use Bluetooth: macOS kills a process without a usage
# description. Usage: re/build_probe_app.sh <output.app> <venv python>
set -eu
APP=$1
PY=$2
get() { "$PY" -c "import sysconfig; print(sysconfig.get_config_var('$1'))"; }
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>local.whoop5.probe</string>
<key>CFBundleName</key><string>WhoopProbe</string>
<key>CFBundleExecutable</key><string>whoopprobe</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSBackgroundOnly</key><true/>
<key>NSBluetoothAlwaysUsageDescription</key><string>Reads your own WHOOP strap for wearable5.0.</string>
</dict></plist>
PLIST
SRC=$(mktemp -t whoopprobe).c
printf '#include <Python.h>\nint main(int argc, char **argv) { return Py_BytesMain(argc, argv); }\n' > "$SRC"
clang -I"$(get INCLUDEPY)" "$SRC" -o "$APP/Contents/MacOS/whoopprobe" -F"$(get PYTHONFRAMEWORKPREFIX)" -framework Python \
  -Wl,-rpath,"$(get PYTHONFRAMEWORKPREFIX)"
rm -f "$SRC"
codesign --force -s - --deep "$APP"
echo "built $APP"

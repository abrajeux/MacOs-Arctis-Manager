#!/bin/sh
# Build "Arctis Manager.app" for personal use.
#
# macOS protects ~/Documents (TCC), so an app launched via Finder/Login Items
# cannot read a venv living there. We therefore install a *copy* of the app into
# a runtime venv OUTSIDE ~/Documents (~/.local/share/arctis-manager, no spaces so
# venv shebangs stay valid) and point a thin .app at it. Nothing under ~/Documents
# is read at runtime.
#
# Re-run this after changing the code to refresh the installed copy.
#
# Usage: scripts/make_macos_app.sh [install-dir]   (default: ~/Applications)
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${ARCTIS_RUNTIME:-$HOME/.local/share/arctis-manager}"
VENV="$RUNTIME/venv"
APP="${1:-$HOME/Applications}/Arctis Manager.app"

echo "Provisioning runtime venv at $VENV ..."
rm -rf "$VENV"
mkdir -p "$RUNTIME"
uv venv "$VENV" >/dev/null
uv pip install --python "$VENV/bin/python" "$REPO" >/dev/null
echo "Installed app copy into runtime venv."

echo "Building $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Arctis Manager</string>
    <key>CFBundleDisplayName</key><string>Arctis Manager</string>
    <key>CFBundleIdentifier</key><string>com.abrajeux.arctis-manager</string>
    <key>CFBundleExecutable</key><string>arctis-manager</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundleVersion</key><string>0.1.0</string>
    <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/arctis-manager" <<LAUNCH
#!/bin/sh
exec "$VENV/bin/python" -m macos_arctis_manager.menubar
LAUNCH
chmod +x "$APP/Contents/MacOS/arctis-manager"

echo "Built: $APP"

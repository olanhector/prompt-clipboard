#!/bin/bash
# Build PromptClipboard.app — a bundle you can drag anywhere, including
# /Applications. Nothing outside the bundle is referenced at runtime.
#
#   ./build_app.sh                 borrow a Tk-capable python3 from the host
#   ./build_app.sh --embed-python  ship a private Python inside the bundle
#
# The plain build is fine on a machine that already has a Tk 8.6+ python3.
# --embed-python is what a copy handed to someone else needs: it runs on a Mac
# with no Python at all, at the cost of ~70 MB.
set -e
cd "$(dirname "$0")"

APP="PromptClipboard.app"
CONTENTS="$APP/Contents"

EMBED_PYTHON=0
for arg in "$@"; do
  case "$arg" in
    --embed-python) EMBED_PYTHON=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

# 1. Icon ---------------------------------------------------------------------
if [ ! -f AppIcon.png ]; then
  python3 make_icon.py
fi

ICONSET="AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512 1024; do
  sips -z $size $size AppIcon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
done
cp "$ICONSET/icon_32x32.png"     "$ICONSET/icon_16x16@2x.png"
cp "$ICONSET/icon_64x64.png"     "$ICONSET/icon_32x32@2x.png"
cp "$ICONSET/icon_256x256.png"   "$ICONSET/icon_128x128@2x.png"
cp "$ICONSET/icon_512x512.png"   "$ICONSET/icon_256x256@2x.png"
cp "$ICONSET/icon_1024x1024.png" "$ICONSET/icon_512x512@2x.png"
rm -f "$ICONSET/icon_64x64.png" "$ICONSET/icon_1024x1024.png"
iconutil -c icns "$ICONSET" -o AppIcon.icns
rm -rf "$ICONSET"

# 2. Bundle -------------------------------------------------------------------
rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
cp AppIcon.icns        "$CONTENTS/Resources/AppIcon.icns"
cp prompt_clipboard.py "$CONTENTS/Resources/prompt_clipboard.py"

# First-run seed only. The live phrase file lives in Application Support.
if [ -f ../clipboard_widget/phrases.json ]; then
  cp ../clipboard_widget/phrases.json "$CONTENTS/Resources/phrases.seed.json"
fi

# The identifier stays in the local.* namespace: this is not published through
# a Meta-managed channel, so it should not claim a com.meta.* one.
#
# No LSUIElement: v1 set it, which left the app with no Dock icon, no Cmd-Tab
# entry and no way to quit when the window failed to draw.
cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>PromptClipboard</string>
  <key>CFBundleDisplayName</key>       <string>Prompt Clipboard</string>
  <key>CFBundleIdentifier</key>        <string>local.promptclipboard</string>
  <key>CFBundleVersion</key>           <string>3.0</string>
  <key>CFBundleShortVersionString</key><string>3.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleSignature</key>         <string>PCLX</string>
  <key>CFBundleExecutable</key>        <string>launch</string>
  <key>CFBundleIconFile</key>          <string>AppIcon</string>
  <key>NSHighResolutionCapable</key>   <true/>
  <key>LSApplicationCategoryType</key> <string>public.app-category.productivity</string>
  <key>LSMinimumSystemVersion</key>    <string>10.13</string>
</dict>
</plist>
PLIST

# Runs only the copy inside the bundle, so location on disk is irrelevant.
cat > "$CONTENTS/MacOS/launch" <<'LAUNCH'
#!/bin/bash
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$BUNDLE/Contents/Resources/prompt_clipboard.py"
LOG="$HOME/Library/Logs/PromptClipboard.log"
mkdir -p "$(dirname "$LOG")"

alert() {
  /usr/bin/osascript -e "display alert \"Prompt Clipboard\" message \"$1\"" >/dev/null 2>&1
  exit 1
}

[ -f "$SCRIPT" ] || alert "Bundle is incomplete: prompt_clipboard.py is missing."

PY=""
# A runtime shipped inside the bundle wins, so a self-contained build never
# depends on whatever the host happens to have installed.
EMBEDDED="$BUNDLE/Contents/Resources/python/bin/python3"
if [ -x "$EMBEDDED" ]; then
  PY="$EMBEDDED"
else
  # Tk 8.6+ is REQUIRED, not merely preferred. Apple's /usr/bin/python3 still
  # ships Tk 8.5.9 (2010), which on current macOS draws native buttons but
  # leaves every custom-coloured frame, label, entry and text blank. An 8.5
  # interpreter looks perfectly healthy to `import tkinter`, so check version.
  for CANDIDATE in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$CANDIDATE" ] || continue
    "$CANDIDATE" -c 'import sys, tkinter; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' \
      >/dev/null 2>&1 || continue
    PY="$CANDIDATE"
    break
  done
fi

[ -n "$PY" ] || alert "No python3 with Tk 8.6 or newer was found. Apple's system python3 ships Tk 8.5, which cannot draw this window. Install a newer one, e.g.: brew install python-tk"

# Arguments mean a CLI invocation (--selftest, --doctor), so keep the terminal
# and skip the log. Lets the shipped bundle be verified without a display.
if [ "$#" -gt 0 ]; then
  exec "$PY" "$SCRIPT" "$@"
fi
exec "$PY" "$SCRIPT" >>"$LOG" 2>&1
LAUNCH
chmod +x "$CONTENTS/MacOS/launch"

# 3. Private Python -----------------------------------------------------------
# py2app is the usual tool here and does not work for this app: it expects a
# framework build whose zlib is a shared module, and the Pythons available are
# Apple's (Tk 8.5, too old) and fbpython (Meta infra, not ours to ship).
# python-build-standalone is built to be relocated, so copying it in is both
# simpler and more predictable. uv is just the most convenient way to fetch it.
if [ "$EMBED_PYTHON" = "1" ]; then
  command -v uv >/dev/null 2>&1 || {
    echo "ERROR: --embed-python needs uv to fetch a relocatable Python." >&2
    echo "Install it from https://docs.astral.sh/uv/ and re-run." >&2
    exit 1
  }
  uv python install 3.13 >/dev/null 2>&1 || true
  RUNTIME_BIN="$(uv python find 3.13 2>/dev/null || true)"
  [ -n "$RUNTIME_BIN" ] || { echo "ERROR: no uv-managed Python 3.13 found." >&2; exit 1; }
  # pwd -P, not pwd: uv hands out a symlinked path, and copying the link
  # instead of the tree builds a bundle that only runs on this machine.
  RUNTIME_ROOT="$(cd "$(dirname "$RUNTIME_BIN")/.." && pwd -P)"

  "$RUNTIME_BIN" -c 'import sys,tkinter; sys.exit(0 if tkinter.TkVersion>=8.6 else 1)' || {
    echo "ERROR: $RUNTIME_BIN has no usable Tk; refusing to ship a blank window." >&2
    exit 1
  }

  rm -rf "$CONTENTS/Resources/python"
  cp -R "$RUNTIME_ROOT" "$CONTENTS/Resources/python"
  # Build caches from the host are dead weight in a shipped bundle.
  find "$CONTENTS/Resources/python" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

  # Anything reaching outside the bundle works here and breaks everywhere else,
  # which is the failure mode this whole step exists to prevent. Check for it.
  EMBED_DIR="$CONTENTS/Resources/python"
  [ -d "$EMBED_DIR" ] && [ ! -L "$EMBED_DIR" ] || {
    echo "ERROR: embedded runtime is a link, not a copy." >&2; exit 1; }
  if find "$EMBED_DIR" -type l -exec readlink {} \; 2>/dev/null | grep -q '^/'; then
    echo "ERROR: embedded runtime has absolute symlinks; it would not survive a copy." >&2
    exit 1
  fi
  echo "Embedded $("$EMBED_DIR/bin/python3" -V) ($(du -sh "$EMBED_DIR" | cut -f1))"
fi

# 4. Ad-hoc sign — unsigned bundles get a generic icon and Gatekeeper warnings.
#    Must come after the runtime is in place, or the signature won't match.
#    Ad-hoc is enough for a locally built copy; a downloaded one needs a real
#    Developer ID signature and notarisation.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 \
    && echo "Signed (ad-hoc)." \
    || echo "WARNING: ad-hoc signing failed; the icon may not render."
fi

touch "$APP"
echo "Built $(pwd)/$APP ($(du -sh "$APP" | cut -f1))"
echo "Drag it to /Applications, or run: open '$(pwd)/$APP'"

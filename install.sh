#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
APP_PATH="/Applications/eBay Advisor.app"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║      eBay Listing Advisor Setup      ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Python check ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "❌  Python 3 not found. Install it from python.org and re-run this script."
  exit 1
fi
echo "✅  Python $(python3 --version | awk '{print $2}')"

# ── Virtualenv ────────────────────────────────────────────────────────────────
echo "📦  Creating virtual environment…"
python3 -m venv "$VENV"
source "$VENV/bin/activate"

# ── Dependencies ──────────────────────────────────────────────────────────────
echo "📥  Installing dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ── Playwright browsers ───────────────────────────────────────────────────────
echo "🌐  Installing Playwright browsers (Chromium)…"
python -m playwright install chromium

# ── macOS .app bundle ─────────────────────────────────────────────────────────
echo "🍎  Creating eBay Advisor.app in /Applications…"

LAUNCHER="$SCRIPT_DIR/launcher.sh"
cat > "$LAUNCHER" << SHELL
#!/bin/bash
source "$VENV/bin/activate"
python "$SCRIPT_DIR/ebay_advisor.py"
SHELL
chmod +x "$LAUNCHER"

# Build AppleScript app — opens Terminal so tkinter GUI renders correctly
ASCRIPT=$(mktemp /tmp/ebay_advisor_XXXXXX.scpt)
cat > "$ASCRIPT" << APPLESCRIPT
tell application "Terminal"
    activate
    set w to do script "${LAUNCHER}"
    set custom title of w to "eBay Listing Advisor"
end tell
APPLESCRIPT

osacompile -o "$APP_PATH" "$ASCRIPT"
rm "$ASCRIPT"

# Swap in a nicer icon if one exists
if [ -f "$SCRIPT_DIR/icon.icns" ]; then
  cp "$SCRIPT_DIR/icon.icns" "$APP_PATH/Contents/Resources/droplet.icns"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║          Installation Complete!      ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "▶  'eBay Advisor' has been added to /Applications."
echo "   You can also drag it to your Dock for quick access."
echo ""
echo "First run:"
echo "  1. Open eBay Advisor from /Applications (or Launchpad)"
echo "  2. Click 'Set / Change API Key' and paste your Anthropic key"
echo "     (get one at https://console.anthropic.com)"
echo "  3. Make sure Chrome is open and signed in to eBay"
echo "  4. Click 'Analyse My Listings'"
echo ""

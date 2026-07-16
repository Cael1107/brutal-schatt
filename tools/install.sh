#!/usr/bin/env bash
# Install all Schatten Brutal toolchain dependencies.
# Idempotent — safe to re-run.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-$HOME/.openclaw/workspace}"

echo "════════════════════════════════════════════════════════"
echo "  Schatten Brutal — Toolchain Installer"
echo "════════════════════════════════════════════════════════"
echo ""

# Python packages
echo "[1/4] Installing Python packages..."
pip3 install --break-system-packages --quiet \
    requests \
    PyJWT \
    playwright \
    playwright-stealth \
    camoufox \
    beautifulsoup4 \
    python-nmap 2>&1 | tail -3 || true

# Playwright browser
echo ""
echo "[2/4] Installing Playwright browsers..."
python3 -m playwright install chromium 2>&1 | tail -5 || true
python3 -m playwright install-deps chromium 2>&1 | tail -5 || true

# System tools
echo ""
echo "[3/4] Installing system security tools..."
SYSTEM_TOOLS=(nmap sqlmap nikto nuclei)
for tool in "${SYSTEM_TOOLS[@]}"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "  Installing $tool..."
        apt-get install -y --no-install-recommends "$tool" 2>/dev/null || echo "  ⚠ $tool install failed (apt may be locked)"
    else
        echo "  ✓ $tool already installed"
    fi
done

# Optional: dirb, wfuzz, whatweb (apt may have version conflicts)
for tool in dirb wfuzz whatweb; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "  Trying $tool..."
        apt-get install -y --no-install-recommends "$tool" 2>/dev/null && echo "  ✓ $tool installed" || echo "  ⚠ $tool skipped"
    else
        echo "  ✓ $tool already installed"
    fi
done

# Hackingtool reference repo (clone only, not used directly)
echo ""
echo "[4/4] Cloning hackingtool reference repo..."
HT_DIR="$WORKSPACE/.tools/hackingtool"
if [ ! -d "$HT_DIR" ]; then
    git clone --depth 1 https://github.com/Z4nzu/hackingtool.git "$HT_DIR" 2>&1 | tail -3
else
    echo "  ✓ hackingtool already cloned at $HT_DIR"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Installation complete"
echo ""
echo "  Quick test:"
echo "    python3 $SCRIPT_DIR/jwt-forge.py --help"
echo "    python3 $SCRIPT_DIR/noqli.py --help"
echo "    python3 $SCRIPT_DIR/race-test.py --help"
echo "    python3 $SCRIPT_DIR/browser-harvest.py --help"
echo "    python3 $SCRIPT_DIR/schatten-run.py --help"
echo "════════════════════════════════════════════════════════"

#!/usr/bin/env bash
# AlphaSignal — one-click launcher (macOS / Linux)
#
# What it does:
#   1. Builds the React frontend into frontend/dist/ (skipped if already built)
#   2. Starts the FastAPI backend, which serves the built frontend at http://localhost:8000
#   3. Opens the app in Chrome "app mode" (no address bar — native-window feel)
#      or falls back to Safari / your default browser if Chrome isn't installed.
#
# Usage:
#   bash scripts/launch.sh            # normal launch (rebuild only if dist is missing)
#   bash scripts/launch.sh --rebuild  # force a fresh frontend build first
#
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
DIST="$REPO_ROOT/frontend/dist"
PORT=8000

# ── 1. Activate virtual environment ───────────────────────────────────────────
if [ -f "$VENV/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
else
    echo "ERROR: virtual environment not found at $VENV"
    echo "       Run: python3.11 -m venv .venv && source .venv/bin/activate && pip install -e .[dev]"
    exit 1
fi

# ── 2. Build frontend if needed ────────────────────────────────────────────────
if [ ! -f "$DIST/index.html" ] || [ "${1:-}" = "--rebuild" ]; then
    echo "==> Building frontend (this takes ~30 seconds the first time)..."
    cd "$REPO_ROOT/frontend"
    npm install --silent
    npm run build
    cd "$REPO_ROOT"
    echo "==> Frontend built successfully."
fi

# ── 3. Open in browser after the server starts ────────────────────────────────
(sleep 2 && {
    URL="http://localhost:$PORT"
    # Chrome "app mode" hides the address bar for a desktop-app feel.
    # Try Google Chrome, then Chromium, then fall back to whatever `open` uses.
    if open -Ra "Google Chrome" 2>/dev/null; then
        open -na "Google Chrome" --args --app="$URL"
    elif open -Ra "Chromium" 2>/dev/null; then
        open -na "Chromium" --args --app="$URL"
    else
        open "$URL"
    fi
}) &

echo ""
echo "============================================================"
echo "  AlphaSignal — http://localhost:$PORT"
echo "  Press Ctrl-C to stop."
echo "============================================================"
echo ""

# ── 4. Start backend (serves API + static frontend on port 8000) ──────────────
cd "$REPO_ROOT"
exec uvicorn backend.app.main:app --port "$PORT" --host 0.0.0.0

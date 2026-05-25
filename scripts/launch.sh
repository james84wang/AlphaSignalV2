#!/usr/bin/env bash
# AlphaSignal — one-click launcher (macOS / Linux)
#
# What it does:
#   1. Activates the Python virtual environment.
#   2. Builds the React frontend into frontend/dist/ when source has changed
#      (or always, if --rebuild is passed).
#   3. Starts the FastAPI backend on port 8000, which also serves the built
#      frontend at the same URL — no separate frontend process needed.
#   4. Opens the app in your browser (Chrome app-mode if available).
#
# Usage:
#   bash scripts/launch.sh            # auto-rebuilds only when source changed
#   bash scripts/launch.sh --rebuild  # force a fresh frontend build
#   bash scripts/launch.sh --no-build # skip build check (fastest cold-start)
#
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
DIST="$REPO_ROOT/frontend/dist"
SRC="$REPO_ROOT/frontend/src"
PORT=8000
ARG="${1:-}"

# ── 1. Activate virtual environment ───────────────────────────────────────────
if [ ! -f "$VENV/bin/activate" ]; then
    echo ""
    echo "ERROR: Python virtual environment not found at .venv/"
    echo ""
    echo "Set it up once with:"
    echo "  cd $(basename "$REPO_ROOT")"
    echo "  python3.11 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -e .[dev]"
    echo ""
    exit 1
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# ── 2. Frontend build ──────────────────────────────────────────────────────────
needs_build() {
    # Rebuild if dist/index.html doesn't exist ...
    [ ! -f "$DIST/index.html" ] && return 0
    # ... or if any file under frontend/src/ is newer than the last build.
    [ -n "$(find "$SRC" -newer "$DIST/index.html" -type f 2>/dev/null | head -1)" ] && return 0
    return 1
}

if [ "$ARG" = "--no-build" ]; then
    echo "==> Skipping frontend build (--no-build)."
elif [ "$ARG" = "--rebuild" ] || needs_build; then
    echo "==> Building frontend..."
    cd "$REPO_ROOT/frontend"
    # Use pnpm if available (required after mod-g switched package manager),
    # fall back to npm only if pnpm is not installed.
    if command -v pnpm &>/dev/null; then
        pnpm install --frozen-lockfile --silent
        pnpm run build
    else
        npm install --silent
        npm run build
    fi
    cd "$REPO_ROOT"
    echo "==> Frontend built."
else
    echo "==> Frontend is up to date, skipping build."
fi

# ── 3. Open in browser after the server starts ────────────────────────────────
# Use --new-window so Chrome never restores a stale cached app-mode session.
# The backend sends Cache-Control: no-cache on index.html, and every build
# embeds a unique timestamp in the JS bundle filename, so stale-cache issues
# are eliminated end-to-end.
(sleep 3 && {
    URL="http://localhost:$PORT"
    if open -Ra "Google Chrome" 2>/dev/null; then
        open -na "Google Chrome" --args --new-window --app="$URL" 2>/dev/null || open "$URL"
    elif open -Ra "Chromium" 2>/dev/null; then
        open -na "Chromium" --args --new-window --app="$URL" 2>/dev/null || open "$URL"
    else
        open "$URL" 2>/dev/null || true
    fi
}) &

echo ""
echo "============================================================"
echo "  AlphaSignal"
echo "  http://localhost:$PORT"
echo ""
echo "  Press Ctrl-C to stop."
echo "============================================================"
echo ""

# ── 4. Start backend (serves API + built frontend on port 8000) ───────────────
cd "$REPO_ROOT"
exec uvicorn backend.app.main:app --port "$PORT" --host 127.0.0.1

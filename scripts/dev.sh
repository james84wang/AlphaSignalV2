#!/usr/bin/env bash
# Start backend (FastAPI) and frontend (Vite) in parallel.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Starting AlphaSignal dev servers..."
echo "    Backend:  http://localhost:8000"
echo "    Frontend: http://localhost:5173"
echo "    Press Ctrl-C to stop both."
echo ""

# Backend
cd "$REPO_ROOT"
uvicorn backend.app.main:app --reload --port 8000 &
BACKEND_PID=$!

# Frontend
cd "$REPO_ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

# Kill both on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM EXIT

wait

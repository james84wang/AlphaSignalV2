#!/usr/bin/env bash
# Thin wrapper used by cron (or any scheduler) to run the daily signal scan.
#
# Cron doesn't load your shell config, so we:
#   1. Set the repo root explicitly from this script's location.
#   2. Activate the virtual environment.
#   3. Run run_daily.py from the repo root.
#
# Log file: ../data/daily_run.log  (one level above the repo, alongside signals.db)
# Redirect stdout+stderr to that log from your crontab, e.g.:
#   0 8 * * 2-6 /path/to/scripts/run_daily_cron.sh >> /path/to/data/daily_run.log 2>&1
#
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv/bin/activate"
LOG_DIR="$(dirname "$REPO_ROOT")/data"

echo "--- run_daily_cron.sh started at $(date) ---"

if [ ! -f "$VENV" ]; then
    echo "ERROR: venv not found at $VENV — aborting."
    exit 1
fi

# shellcheck disable=SC1090
source "$VENV"

cd "$REPO_ROOT"
python scripts/run_daily.py

echo "--- run_daily_cron.sh finished at $(date) ---"

# AlphaSignal

Personal US equity analysis and trading strategy engine.

---

## Prerequisites

### macOS

**1. Install Python 3.11+**
```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/homebrew/install/HEAD/install.sh)"

# Install Python 3.11
brew install python@3.11
```

**2. Install Node.js LTS**
```bash
brew install node
```

---

### Windows

**1. Install Python 3.11+**
- Download from https://www.python.org/downloads/
- During install, tick **"Add Python to PATH"** before clicking Install Now.

**2. Install Node.js LTS**
- Download from https://nodejs.org/en/download/
- Run the installer with default settings.

---

## Setup (macOS & Windows)

### 1. Create the Python virtual environment

**macOS / Linux:**
```bash
cd AlphaSignalV2
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Windows (PowerShell):**
```powershell
cd AlphaSignalV2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 2. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Run

### macOS / Linux — one command:
```bash
bash scripts/dev.sh
```

### Windows — one command:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Open **http://localhost:5173** in your browser. The full UI loads with Dashboard, Symbol view, Settings, and Backtest pages.

---

## Run tests

```bash
# Make sure .venv is active first
pytest -q
```

---

## Data layer (Phase 1)

### Fetch demo — download 5 years of AAPL/MSFT/NVDA and cache as Parquet

```bash
python scripts/fetch_demo.py
```

The first run fetches from Yahoo Finance. Every run after that is served from local
Parquet files under `data/bars/`. Re-running for already-cached symbols is near-instant.

### Watchlist

Create `data/watchlist.csv` with this header and one symbol per row:

```
symbol,exchange
AAPL,NASDAQ
MSFT,NASDAQ
NVDA,NASDAQ
```

### Finnhub (optional — real-time quotes)

1. Get a free API key at https://finnhub.io
2. Create a file called `.env` in the repo root:
   ```
   FINNHUB_API_KEY=your_key_here
   ```
3. The app loads this automatically. If the key is absent, Finnhub is silently disabled.

---

## Daily Signal Runner (Phase 3)

### Run today's signals for your watchlist

```bash
# From the AlphaSignalV2/ directory, with .venv active:
python scripts/run_daily.py
```

This fetches/refreshes data for every symbol in `data/watchlist.csv`, scores each
one, prints a ranked table, and saves everything to SQLite at
`../data/signals.db` (one directory above the repo, alongside the Parquet cache).

### Common options

```bash
# Use the full S&P 500 (~500 symbols) instead of just your watchlist:
python scripts/run_daily.py --universe sp500

# Score a specific historical date:
python scripts/run_daily.py --date 2025-03-15

# Verbose (shows data-fetch progress):
python scripts/run_daily.py --verbose
```

### Inspect stored results

```bash
# Show latest run's ranked signals:
python scripts/query_signals.py

# List all past runs:
python scripts/query_signals.py --list-runs

# Drill into per-component sub-scores for one symbol:
python scripts/query_signals.py --symbol AAPL

# Show a specific run by ID:
python scripts/query_signals.py --run 3
```

### Direct SQL (optional)

If you prefer raw SQL, the database is a standard SQLite file:

```bash
sqlite3 ../data/signals.db
```

```sql
-- Latest run's signals ranked by composite score
SELECT s.symbol, s.signal, s.composite, s.long_allowed, s.short_allowed,
       s.sub_scores_json
FROM signals s
JOIN runs r ON s.run_id = r.id
WHERE r.id = (SELECT MAX(id) FROM runs)
ORDER BY s.composite DESC;

-- All Strong Buy / Buy signals across all runs
SELECT r.run_timestamp, r.universe, s.symbol, s.signal, s.composite
FROM signals s JOIN runs r ON s.run_id = r.id
WHERE s.signal IN ('Strong Buy', 'Buy')
ORDER BY r.run_timestamp DESC, s.composite DESC;

-- Inspect sub-scores for a specific symbol
SELECT s.symbol, s.date, s.composite, s.sub_scores_json
FROM signals s
WHERE s.symbol = 'GS'
ORDER BY s.run_id DESC LIMIT 5;
```

### Watchlist

Edit `data/watchlist.csv` to add or remove symbols:

```
symbol,exchange
AAPL,NASDAQ
MSFT,NASDAQ
NVDA,NASDAQ
GS,NYSE
```

---

## Backtest Engine (Phase 4)

### Run a backtest for your watchlist (one command)

```bash
# From the AlphaSignalV2/ directory, with .venv active:
python scripts/run_backtest.py
```

Fetches/caches OHLCV data, walks bar-by-bar through history (default: 5 years),
simulates entries and exits using the default config weights, and prints a full
performance report. Results are saved to SQLite automatically.

### Common options

```bash
# Run a 3-year backtest instead of 5
python scripts/run_backtest.py --years 3

# Use a custom starting capital
python scripts/run_backtest.py --account 50000

# Skip SQLite persistence (just print the report)
python scripts/run_backtest.py --no-save
```

### Backtest parameters (config.yaml)

All backtest parameters live under the `backtest:` key in `config.yaml`:

```yaml
backtest:
  start_years_back: 5        # default lookback window
  initial_account: 100000    # starting capital
  slippage_pct: 0.001        # 0.1% slippage per fill
  commission_per_trade: 1.0  # $1 flat commission per fill
```

Risk rules (stop-loss, position sizing, max positions, cooldown) are in
`config.yaml` under `risk:`. Changing any weight or threshold and re-running
`run_backtest.py` shows the impact immediately.

### Inspect stored backtest results

```bash
sqlite3 ../data/signals.db
```

```sql
-- List all backtest runs
SELECT id, run_timestamp, metrics_json FROM backtest_runs ORDER BY id DESC;

-- Trade log for the latest run
SELECT symbol, side, entry_date, exit_date, pnl, exit_reason
FROM backtest_trades WHERE run_id = (SELECT MAX(id) FROM backtest_runs);

-- Equity curve for run #1
SELECT date, equity FROM backtest_equity WHERE run_id = 1 ORDER BY date;
```

### Notes on no look-ahead bias

- Signal at bar T uses ONLY data available at the close of bar T.
- Entries fill at bar T+1's open (never T's close).
- Stop-loss uses intrabar high/low, not just open/close.
- Unit tests in `backend/tests/backtest/test_engine.py` prove all three.

### Notes on survivorship bias

The default watchlist reflects **currently surviving** companies. Companies
delisted or acquired during the backtest period are excluded — this inflates
performance metrics. The engine prints a reminder on every run.

### Notes on earnings blackout

The spec calls for skipping signals within 3 bars of earnings. This requires
a Finnhub API key (`FINNHUB_API_KEY` env var). Without one, the rule is
disabled and noted in the backtest output.

---

## Project layout

```
AlphaSignalV2/
  config.yaml          # all strategy weights & thresholds — edit here
  pyproject.toml       # Python deps
  data/                # local cache (git-ignored)
    bars/              # one .parquet file per symbol
    watchlist.csv      # your personal watchlist
    sp500.csv          # S&P 500 list (auto-fetched once)
    signals.db         # SQLite: runs + signals tables (Phase 3)
  backend/
    app/
      main.py          # FastAPI entry (GET /health)
      config.py        # loads & validates config.yaml
      data/
        provider.py        # abstract MarketDataProvider interface
        yfinance_provider.py  # primary source (Yahoo Finance)
        finnhub_provider.py   # secondary source stub (real-time quotes)
        cache.py           # Parquet read-through cache
        universe.py        # S&P 500 + user watchlist management
      db/
        models.py          # SQLAlchemy ORM: Run + Signal tables (Phase 3)
        backtest_models.py # SQLAlchemy ORM: BacktestRun/Trade/Equity (Phase 4)
      backtest/
        engine.py          # walk-forward backtest engine (Phase 4)
        metrics.py         # performance metrics (Phase 4)
    tests/
      data/            # unit tests for the data layer (no network)
      db/              # unit tests for the db layer (Phase 3)
      backtest/        # anti-look-ahead + mechanics tests (Phase 4)
  frontend/
    src/
      App.tsx          # router root
      main.tsx         # QueryClientProvider + BrowserRouter
      vite-env.d.ts    # Vite type declarations
      lib/
        api.ts         # typed API client (all endpoints)
        types.ts       # shared TypeScript interfaces
        indicators.ts  # client-side EMA / MACD / RSI
        queryClient.ts # TanStack Query config
      components/
        Layout.tsx     # app shell: sidebar, nav, universe selector, footer
        ChartPanel.tsx # synchronized candlestick + MACD + RSI charts
        AuditPanel.tsx # per-bar score breakdown panel
        SignalBadge.tsx # color-coded signal badge + helpers
        ErrorState.tsx # reusable error display
        LoadingState.tsx
      pages/
        Dashboard.tsx  # ranked signal table → click to Symbol view
        SymbolView.tsx # chart + audit panel for one symbol
        Settings.tsx   # weight sliders, threshold display, scoring tables
        Backtest.tsx   # backtest form, equity curve, metrics, trade log
  scripts/
    fetch_demo.py      # download 5yr bars for AAPL/MSFT/NVDA
    run_engine.py      # run scoring engine for a single symbol (debug)
    run_daily.py       # daily signal runner: universe → SQLite (Phase 3)
    run_backtest.py    # backtest runner (Phase 4)
    query_signals.py   # inspect stored results without writing SQL (Phase 3)
    dev.sh             # start both servers (mac/linux, dev mode)
    dev.ps1            # start both servers (windows, dev mode)
    launch.sh          # one-click production launcher (mac/linux, Phase 7)
    launch.ps1         # one-click production launcher (windows, Phase 7)
    run_daily_cron.sh  # cron wrapper for scheduled daily scan (Phase 7)
  trading_strategy_spec.md
  config.yaml
```

---

## Desktop Launcher (Phase 7)

### Trade-off: pywebview vs Tauri vs Electron vs Simple Launcher

| Option | Window | New deps | Bundling to .app/.exe | Verdict |
|---|---|---|---|---|
| **Simple launcher** (our choice) | Chrome app mode (no address bar) | none | not needed | Easiest. Zero new Python deps. Works today. |
| **pywebview** | True native WebView window | `pip install pywebview` | PyInstaller — complex, fragile on Apple Silicon | Good choice once bundling matters |
| **Tauri** | True native window, tiny bundles | Rust toolchain | `cargo tauri build` | Best end-result but requires Rust; Python subprocess is awkward |
| **Electron** | Chromium window | Node + Electron | `electron-builder` | Very heavy (~150 MB); Node managing a Python process is messy |

**Why simple launcher wins for now:** The app already runs in a browser. Chrome's `--app` flag removes the address bar and gives it its own taskbar entry — indistinguishable from a desktop app for daily use. No new tools, no bundling, no breakage.

---

### First-time setup (do this once)

Build the React frontend into a static bundle that the backend will serve:

```bash
# From the AlphaSignalV2/ directory, with .venv active:
cd frontend
npm run build
cd ..
```

This creates `frontend/dist/`. You only need to redo this if you change frontend code.

---

### Launch the app (macOS)

```bash
bash scripts/launch.sh
```

The script will:
1. Check the virtual environment is active.
2. Build the frontend if `frontend/dist/` is missing.
3. Start the backend on port 8000 (it serves the built frontend too — no Vite needed).
4. Open the app in Chrome app-mode (no address bar). Falls back to Safari.

To force a fresh frontend rebuild:
```bash
bash scripts/launch.sh --rebuild
```

---

### Launch the app (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch.ps1
```

To force a rebuild:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 -Rebuild
```

---

### Development mode vs Production mode

| | Dev mode (`dev.sh`) | Production mode (`launch.sh`) |
|---|---|---|
| Servers | Backend on :8000, Vite on :5173 | Backend only on :8000 |
| Hot reload | Yes | No (rebuild needed) |
| Open URL | http://localhost:5173 | http://localhost:8000 |
| Use for | Active frontend development | Normal daily use |

---

## Scheduled Daily Run (Phase 7)

US market closes at **4:00 PM ET**. In your timezone (AEST/AEDT), that is:

| US season | US time | UTC | AEST (UTC+10) | AEDT (UTC+11) |
|---|---|---|---|---|
| Summer (Apr–Oct, EDT) | 4 PM EDT | 8 PM | 6 AM **next day** | 7 AM **next day** |
| Winter (Oct–Apr, EST) | 4 PM EST | 9 PM | 7 AM **next day** | 8 AM **next day** |

Recommended run time: **8 AM local time, Tuesday–Saturday** (captures Mon–Fri US closes).

---

### macOS — cron setup (exact steps)

**Step 1 — Find your Python and repo paths**

Open Terminal and run these two commands. Copy the output — you'll need it below.

```bash
# Full path to the Python in your venv:
echo /Users/jameswang/Documents/Claude/Code/AlphaSignalV2/.venv/bin/python

# Full path to the cron wrapper script:
echo /Users/jameswang/Documents/Claude/Code/AlphaSignalV2/scripts/run_daily_cron.sh

# Full path to the log file (one folder above the repo):
echo /Users/jameswang/Documents/Claude/Code/data/daily_run.log
```

**Step 2 — Open your crontab**

```bash
crontab -e
```

This opens `vi`. To insert a new line, press `i` (insert mode), then type the cron entry below. Press `Esc`, then type `:wq` and press Enter to save.

**Step 3 — Paste this cron entry** (replace the paths if yours differ)

```
0 8 * * 2-6 /Users/jameswang/Documents/Claude/Code/AlphaSignalV2/scripts/run_daily_cron.sh >> /Users/jameswang/Documents/Claude/Code/data/daily_run.log 2>&1
```

This runs the scan at **8:00 AM every Tuesday through Saturday** in your local timezone.

**Step 4 — Verify it saved**

```bash
crontab -l
```

You should see the line you just added.

**Step 5 — Allow Terminal to run in the background (macOS only)**

macOS may block cron from running unless you grant it Full Disk Access:

1. Open **System Settings → Privacy & Security → Full Disk Access**
2. Click **+**, navigate to `/usr/sbin/cron`, and add it.
3. Toggle it **On**.

**Step 6 — How to verify it ran**

After 8 AM on a trading day, check the log:

```bash
tail -50 /Users/jameswang/Documents/Claude/Code/data/daily_run.log
```

You should see the ranked signal table printed there. You can also check the database directly:

```bash
cd /Users/jameswang/Documents/Claude/Code/AlphaSignalV2
source .venv/bin/activate
python scripts/query_signals.py --list-runs
```

---

### Windows — Task Scheduler setup (exact steps)

**Step 1 — Open Task Scheduler**

Press `Win + R`, type `taskschd.msc`, press Enter.

**Step 2 — Create a new task**

In the right panel, click **Create Task** (not "Create Basic Task").

**Step 3 — General tab**
- Name: `AlphaSignal Daily Scan`
- Tick **"Run whether user is logged on or not"** if you want it to run even when locked.
- Tick **"Run with highest privileges"**.

**Step 4 — Triggers tab**

Click **New**:
- Begin the task: **On a schedule**
- Settings: **Weekly**
- Start: pick today's date, time = **8:00 AM**
- Recur every **1** weeks
- Tick the days: **Tuesday, Wednesday, Thursday, Friday, Saturday**
- Click OK.

**Step 5 — Actions tab**

Click **New**:
- Action: **Start a program**
- Program/script: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
- Add arguments:
  ```
  -ExecutionPolicy Bypass -File "C:\Users\YourName\Documents\Claude\Code\AlphaSignalV2\scripts\run_daily_cron.ps1"
  ```
  *(Replace `YourName` with your actual Windows username.)*
- Start in: `C:\Users\YourName\Documents\Claude\Code\AlphaSignalV2`

**Step 6 — Create the Windows cron wrapper** (one-time setup)

Create a file at `scripts\run_daily_cron.ps1` with this content
(substituting your real path):

```powershell
Set-Location "C:\Users\YourName\Documents\Claude\Code\AlphaSignalV2"
$log = "..\data\daily_run.log"
"--- run started $(Get-Date) ---" | Tee-Object -Append $log
.\.venv\Scripts\python.exe scripts\run_daily.py 2>&1 | Tee-Object -Append $log
"--- run finished $(Get-Date) ---" | Tee-Object -Append $log
```

**Step 7 — Verify it ran**

Open the log file:
```
notepad C:\Users\YourName\Documents\Claude\Code\data\daily_run.log
```

Or check the Task Scheduler history: right-click the task → **History** → look for "Task completed" with result `0x0` (success).

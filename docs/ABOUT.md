# AlphaSignal — About

<!-- TAB_SPLIT -->
## Overview & Scope

AlphaSignal is a **personal-use** web application for analysing US equities and building/tuning a **long-only swing-trading strategy**. It is **not** commercial software, **not** financial advice, and **not** designed for day trading. It operates on daily price bars and is intended for personal research only.

The app runs a configurable universe of US stocks through the **Hidden-Divergence Confluence** engine — it BUYS pullback higher-lows confirmed by hidden bullish divergence plus a weighted confluence score, and SELLS on bearish divergence / DeMark exhaustion. The user can tune each indicator's score and the buy/sell thresholds, then backtest the result against historical data.

---

### Trading Universe

| Universe | Contents | Notes |
|----------|----------|-------|
| Watchlists | Four user-editable lists: **Watchlist**, **Watchlist - ChinaTech**, **Watchlist - 2**, **Watchlist 3** | Each is editable in Settings and individually backtestable |
| S&P 500 | Current S&P 500 members | Fetched from Wikipedia, cached locally |
| S&P MidCap 400 | Current S&P 400 members | Part of the "S&P 1000" |
| S&P SmallCap 600 | Current S&P 600 members | Part of the "S&P 1000" |
| NASDAQ 100 | Current NASDAQ-100 members | Selectable separately; not included in "combined" |
| Combined | S&P 500 ∪ MidCap 400 ∪ SmallCap 600 ∪ all watchlists, deduplicated | Default universe for scans |

> **All watchlists are part of the trading universe.** Every index universe is unioned with all watchlist symbols, and each watchlist can also be scanned or backtested on its own.

> **Note:** Index lists reflect *current* membership. Point-in-time membership (required to eliminate survivorship bias) is not tracked — see Backtest Details for implications.

---

### Data Sources

| Data | Source | Delay / Notes |
|------|--------|---------------|
| Daily OHLCV price bars (signal scanning) | yfinance / Yahoo Finance | Up to ~1 hour delay on recent bars; daily resolution only |
| Historical bars for backtesting | yfinance / Yahoo Finance | Adjusted total-return prices (dividends included via `auto_adjust=True`) |
| Market overview indices (^GSPC, ^DJI, ^NYA, ^IXIC, ^NDX, ^VIX, XLK, ^SP400, ^SP600) | yfinance fast_info | Cached 15 minutes in-process |
| CNN Fear & Greed Index | CNN dataviz API (`production.dataviz.cnn.io`) | Cached 15 minutes; undocumented endpoint with browser-like headers |
| Index constituent lists (S&P 500, 400, 600, NASDAQ-100) | Wikipedia | Fetched once per session, cached as CSV files in `data/` |

---

### Architecture & Tech Stack

```
Browser
  └─ React 18 + Vite + TypeScript SPA
        ↕ HTTP (REST JSON)
Python FastAPI backend (port 8000)
  ├─ Signal engine  (confirmed pivots → MACD/RSI divergence + DeMark + EMA regime → confluence score)
  ├─ Backtest engine  (walk-forward long-only portfolio simulation)
  ├─ Optimiser  (Optuna TPE search over entry/exit scores + thresholds, with overfitting checks)
  ├─ APScheduler  (optional daily auto-scan)
  └─ Storage
        ├─ SQLite  (runs, signals, watchlists, backtest results)
        └─ Parquet  (price bar cache, one file per symbol)
```

**Backend:** Python 3.11+, FastAPI, uvicorn, pandas, numpy, yfinance, pydantic v2, PyYAML, SQLAlchemy/SQLite, pyarrow, httpx, APScheduler, Optuna (optimiser)

**Frontend:** React 18, Vite, TypeScript, Tailwind CSS, lightweight-charts (TradingView-licensed chart component), TanStack Query, react-router-dom, SheetJS (xlsx export)

**Daily flow:** APScheduler (or manual trigger) → fetch/update Parquet price cache → compute confluence signal for each symbol → store Run + Signal rows in SQLite → frontend fetches on demand

---

### About & Links

**GitHub:** [james84wang/AlphaSignalV2](https://github.com/james84wang/AlphaSignalV2)

**Charts powered by:** [TradingView](https://www.tradingview.com/)

---

<div class="about-author">
  <img src="/james.jpg" alt="James Wang" class="about-photo" onerror="this.style.display='none';document.getElementById('about-initials').style.display='flex'" />
  <div id="about-initials" class="about-initials" style="display:none">JW</div>
  <div class="about-author-text">
    <strong>Created by James Wang</strong><br/>
    May 2026 · Personal research project
  </div>
</div>

<!-- TAB_SPLIT -->
## Strategy Details

AlphaSignal implements one **long-only** swing strategy: **Hidden-Divergence Confluence — Uptrend Swing**. It hunts pullback *entries* inside an established uptrend and exhaustion-based *exits*. Everything is computed on **confirmed bars**, so signals are reliable but arrive a few bars after the actual turn.

> **Mental model: enter at a higher low, exit at a higher high.**

---

### The key concept — hidden vs regular divergence

Divergence = price and momentum disagree at consecutive swing pivots.

| Pattern | Price does | Momentum does | Meaning | Used for |
|---|---|---|---|---|
| **Hidden bullish** | Higher low | Lower low | Pullback selling is exhausting → uptrend resumes | **Entries** |
| **Regular bearish** | Higher high | Lower high | Rally is exhausting at the top | **Exits** |

Momentum is read from the **MACD line** and the **RSI** (two independent lenses).

---

### Regime gate (entries only)

The entry engine is switched **off** unless all of these are true on the current bar:

- EMA-50 is **above** EMA-200 (bullish structure)
- EMA-50 is **rising** (vs `slope_lookback` bars ago)
- EMA-200 is **rising**
- Close is **above EMA-200**

Price is deliberately *not* required to be above EMA-50 — healthy pullbacks tag the fast line, and that is exactly where the best higher-lows form. **Exits are not gated** — they can fire any time, because you may be holding when the regime starts to break.

---

### Entry score (Buy)

A **BUY** fires when (1) the regime gate is true, (2) a hidden bullish divergence (MACD or RSI) is confirmed on the bar, and (3) the entry score reaches the threshold. Each component adds its points if it fired within the entry confluence window.

| Component | Default Score | What it is |
|-----------|:------:|-----------|
| MACD hidden bullish divergence | 35 | Core thesis (momentum via MACD) |
| RSI hidden bullish divergence | 35 | Core thesis, different lens |
| RSI pullback zone (40–55) | 20 | Location filter — confirms a healthy pullback |
| DeMark TD9 buy setup | 10 | Downside-exhaustion booster |
| **Buy threshold** | **65** | Score must reach this to fire a Buy |

An entry always requires at least one genuine divergence — no single supporting indicator can trigger a buy on its own. Raise the threshold toward 70 to force *both* divergences (fewer, higher-conviction signals); lower toward 55 for more frequency.

---

### Exit score (Sell)

A **SELL** fires when (1) a bearish-divergence / DeMark-sell event is confirmed on the bar, and (2) the exit score reaches the (lower) threshold. Exits act on **less evidence** than entries — you protect capital on less proof than you require to commit it.

| Component | Default Score | What it is |
|-----------|:------:|-----------|
| DeMark TD13 sell countdown | 40 | Strong upside exhaustion |
| MACD regular bearish divergence | 35 | Topping momentum |
| RSI regular bearish divergence | 35 | Topping momentum |
| DeMark TD9 sell setup | 20 | Upside exhaustion |
| **Sell threshold** | **35** | Score must reach this to fire a Sell |

Any single bearish divergence (35) or a TD13 countdown (40) fires the exit on its own; a lone TD9 sell (20) needs a partner.

---

### Confluence window & cooldown

The components almost never peak on the *same* bar (MACD and RSI pivots differ; DeMark completes on its own schedule). So each component counts toward the score if it occurred within the **confluence window** of the trigger bar — default **10 bars for entries**, **5 bars for exits**. A **cooldown** equal to the entry window prevents the same pullback from firing multiple buys.

---

### The indicators

- **EMA-50 / EMA-200** — define trend structure and slope (the regime gate).
- **MACD (12/26/9)** — divergence is measured on the MACD line.
- **RSI (14)** — used for divergence and for the 40–55 pullback zone filter.
- **Swing pivots** — a swing low/high confirmed only after `right` bars print to its right. This is what makes signals **non-repainting** (and lagged).
- **DeMark TD Sequential (simplified)** — a trend-exhaustion timer: a **TD9 setup** is 9 consecutive qualifying closes; a **TD13 countdown** is 13 qualifying closes after a setup. TD9 buy boosts an entry; TD9 sell and TD13 sell drive exits.

All scores, thresholds, confluence windows, and indicator parameters are editable in **Settings** and stored in `config.yaml` under the **`hidden_div`** profile.

---

### Config ↔ Pine input mapping

Every leaf key in `config.yaml` (under `strategies.hidden_div`) is named **1:1 with the
TradingView Pine input** so the strategy can be exported to PineScript without guesswork.
Python attribute names stay descriptive; the on-disk / Pine name is the alias.

| Group | Pine input (config key) | Default | Meaning |
|-------|------------------------|:------:|---------|
| Regime | `emaFast` / `emaSlow` / `slopeLook` | 50 / 200 / 5 | fast & slow EMA periods; "rising" lookback |
| Pivots | `lbL` / `lbR` | 5 / 5 | swing-pivot left / right bars (lbR = confirmation lag) |
| Pivots | `minPivGap` / `maxPivGap` | 5 / 60 | min / max bars between the two divergence pivots |
| MACD | `macdFast` / `macdSlow` / `macdSig` | 12 / 26 / 9 | MACD line periods |
| RSI | `rsiLen` / `rsiZoneLo` / `rsiZoneHi` | 14 / 40 / 55 | RSI length; pullback "buy zone" bounds |
| DeMark | `tdSetup` / `tdCountdown` | 9 / 13 | setup & countdown lengths |
| DeMark | `tdFlipLook` / `tdCountLook` | 4 / 2 | setup close-vs-close; countdown close-vs-high/low lookbacks |
| Entry | `wMacd` / `wRsi` / `wZone` / `wTd9` | 35 / 35 / 20 / 10 | entry component scores |
| Entry | `entryThreshold` / `confWin` | 65 / 10 | Buy score threshold; entry confluence window (+ cooldown) |
| Exit | `wMacdX` / `wRsiX` / `wTd13` / `wTd9X` | 35 / 35 / 40 / 20 | exit component scores |
| Exit | `exitThreshold` / `confWinX` | 35 / 5 | Sell score threshold; exit confluence window (+ cooldown) |

> AlphaSignal **generates the Pine Script itself** from `config.yaml`, so the input names above
> and the exported `.pine` are the same source — no guesswork. The names confirmed by the logic
> doc (`slopeLook`, `lbL`/`lbR`, `minPivGap`/`maxPivGap`, `confWin`/`confWinX`,
> `entryThreshold`/`exitThreshold`, `tdFlipLook`) are exact; the remainder (the `w…` score
> names and the EMA/MACD/RSI/DeMark abbreviations) are AlphaSignal's own. If you already have a
> different reference `.pine`, only the input *labels* differ — the logic is identical.

#### Download as Pine Script

Settings ▸ **Download Pine Script** exports the strategy as a TradingView Pine v6 indicator
(`hidden_div_confluence_uptrend.pine`). It is generated on demand from your **saved** config, so
every `input.*()` default equals your current tuned weights/thresholds and matches the Python
backtest exactly. One generator (`backend/app/export/pine.py`) is the single source for both the
download and the copy checked into the repo root. The Pine ports the engine faithfully — regime
gate, confirmed pivots, MACD/RSI hidden-bull & regular-bear divergence, simplified DeMark
TD9/TD13, confluence windows + cooldown, entry/exit scoring — using TradingView built-ins whose
math matches (`ta.ema`, `ta.rsi` (Wilder), `ta.macd`, `ta.pivotlow`/`ta.pivothigh`). Set the
chart's dividend-adjustment to match your data basis. (TradingView-only S/R zone visuals from the
logic doc are intentionally omitted — they don't affect signals.)

#### Port verification

`scripts/port_check_aapl.py` runs the `hidden_div` engine on AAPL daily (last 3 years) and
writes every BUY/SELL **signal event** — date, close, entry/exit score, and which components
fired — to `data/port_check/aapl_signals.csv`. Drop the downloaded `.pine` on the same AAPL
daily chart and the confluence triangles line up with these dates (allowing the `lbR`-bar
confirmation lag). Because all pivots/divergences are detected on **confirmed** bars (signal at
`low + lbR`), an explicit non-repaint test asserts a pivot is **not** detectable until `lbR`
bars after it prints.

---

### Strategy Limitations

- **Daily timeframe only** — not predictive of intraday moves; cannot react to news within the trading day.
- **Lagged by design** — pivots confirm a few bars after the actual low/high (non-repainting trade-off). On daily swing bars a 1–5 bar lag is acceptable.
- **DeMark is simplified** — setup + countdown with basic cancellation; perfection/recycle nuances are omitted.
- **Whipsaw risk** in choppy markets; the EMA-50/200 regime gate reduces but does not eliminate it.
- **User-tuned scores can overfit** the period used to calibrate them — use the optimiser's overfitting checks and out-of-sample validation.
- **No fundamental awareness** — earnings surprises, guidance, and macro events are not in the model (only an optional earnings blackout).

<!-- TAB_SPLIT -->
## Backtest Details & Limitations

The backtest engine simulates a **long-only** walk-forward portfolio — it processes each trading day in sequence, using only information available up to that close, and fills orders at the *next* day's open.

---

### How the Backtest Works

#### Signal & Fill Timing (no look-ahead)

> Signal for bar **T** uses only data from bars 0 … T (confirmed pivots only).
> Entry and exit orders fill at bar **T+1's open price.**

#### Portfolio Simulation

| Parameter | Default (as configured in config.yaml) |
|-----------|:---:|
| Starting capital | $100,000 |
| Position sizing | 8% of current equity per position |
| Minimum position size | $2,000 |
| Per-name capital cap | 30% of equity |
| Max concurrent open positions | 15 |
| Top-N candidates selected per day | 10 (ranked by entry confluence score) |
| ATR stop multiple | 1.5× 14-period ATR |
| Trailing stop | Yes — moves up using today's close |
| Re-entry cooldown after stop-out | 5 bars |

**Entry selection:** On each day, all new **Buy / Strong Buy** signals are ranked by their entry confluence score (higher = more conviction). Only the top 10 candidates proceed to the slot-and-capital check, then fill at tomorrow's open.

**Exits:**
- **ATR stop** hit intrabar (checked against daily high/low) → fills at stop price or open if gapped through
- **Sell signal** on a held position → fills at next day's open
- **End of data** → closes at last bar's close

#### Fees (as configured)

| Parameter | Value |
|-----------|:-----:|
| Per-share fee | $0.005 |
| Minimum per trade | $1.00 |
| Maximum per trade | 1% of trade value |
| Charged on | Both entry **and** exit |
| Slippage | 0.1% applied to fill price |

#### Benchmark

Buy-and-hold **QQQ** from the first available open price, held through the end of the period. Returns use adjusted total-return prices (dividends included) for comparability with the strategy.

#### Price Basis

Both strategy and benchmark use **yfinance adjusted prices** (`auto_adjust=True`) — historical prices are adjusted for splits and dividends, so returns reflect total return including dividends.

---

### Strategy Optimiser (overfitting-aware)

`scripts/optimize.py` searches the entry/exit component scores, the buy/sell thresholds, and (optionally) the confluence windows with Optuna (TPE), then stress-tests the winner:

- **70/30 in-sample / holdout split** and **4-fold walk-forward** validation.
- **Luck audit** (does the winner beat QQQ more often than random configs?), **perturbation test** (does it survive ±10-point score nudges?), and a **top-config cluster check**.
- The live `config.yaml` is **never** auto-modified; winners are written to `config.candidate.long.yaml` for manual review.

---

### Backtest Limitations

- **Data delay & granularity:** Daily bars only; yfinance data may be delayed up to ~1 hour. Not suitable for same-day decision-making or intraday timing.

- **Warm-up:** the EMA-200 regime gate needs 200 bars and swing pivots add a confirmation lag, so the first several months of any window produce few or no signals.

- **SURVIVORSHIP BIAS (important):**
  The S&P 500, MidCap 400, and SmallCap 600 universe lists reflect *current* membership. Companies that were **delisted, went bankrupt, or were removed** during the backtest period are absent — making results look better than they would have been in real time ("fake-good" upward bias). Correcting this requires point-in-time membership data (not available for free). Treat all backtest returns as an **optimistic upper bound**.

- **No liquidity or market-impact modelling:** Thin small-cap stocks may have wide bid/ask spreads. The 0.1% slippage assumption may be optimistic for illiquid names.

- **No borrow cost or tax modelling.**

- **Corporate actions** are handled only via adjusted prices. Mergers, spin-offs, and symbol changes may cause data gaps or discontinuities.

- **Past performance does not predict future results. This backtest is for personal research and strategy understanding only — not investment advice.**

<!-- TAB_SPLIT -->
## Changelog

Entries are reverse-chronological (most recent first).

---

### v0.2.0 — June 2026

**Mod-N (2026-06-09):** **Optimiser UI.** Added an **Optimiser** page (new sidebar tab) that runs the Optuna search from the browser: pick a universe, date range, trial budget, walk-forward folds and seed, with optional toggles to also tune the confluence windows / position sizing. A new async job API (`POST /api/optimize`, `GET /api/optimize/{job_id}`, `…/promote`, `…/report`) runs the search on a background thread and streams live progress (trials completed + phase) to a progress bar, mirroring the backtest job pattern. Results render in-app: the PASS/FAIL overfit verdict + tier, the in-sample/holdout/walk-forward metrics table, the QQQ benchmark row, the anti-overfitting summary (luck audit, cluster, perturbation) and the best entry/exit weights. A guarded **Promote to live config** button (explicit confirm) applies the candidate to `config.yaml` and hot-reloads it; the live config is otherwise never touched. The full markdown report is viewable/downloadable from the page. Added optimiser-API tests (start→poll→result, promote, validation).

**Mod-M (2026-06-09):** **Optimiser verified on the `hidden_div` strategy; candidate config now Pine-aliased.** Confirmed the Optuna optimiser tunes the new entry/exit confluence scores + thresholds end-to-end (`scripts/optimize.py --universe watchlist`), producing the in-sample/holdout/walk-forward report with the PASS/FAIL overfit verdict, luck audit, perturbation and cluster checks. Fixed `save_candidate_config` to write `config.candidate.hidden_div.yaml` with the **Pine alias keys** (`entryThreshold`, `wMacd`, `emaFast`, …) so a promoted candidate stays 1:1 with the live `config.yaml` schema, and corrected stale `--strategy long` text in the optimiser CLI (only `hidden_div` is valid). The live `config.yaml` is never modified; promotion remains a manual copy.

**Mod-L (2026-06-09):** **Download the strategy as a TradingView Pine Script.** Added Settings ▸ *Download Pine Script*, which exports the `hidden_div` strategy as a Pine v6 indicator (`hidden_div_confluence_uptrend.pine`). A single config-driven generator (`backend/app/export/pine.py`, served at `GET /api/config/hidden_div/pine`) bakes every `input.*()` default from the **saved** config, so the exported script reflects your current tuned weights/thresholds and matches the Python backtest. The Pine faithfully ports the engine (regime gate, confirmed swing pivots, MACD/RSI hidden-bull & regular-bear divergence, simplified DeMark TD9/TD13, confluence windows + cooldown, weighted entry/exit scoring) using built-ins whose math matches AlphaSignal's (`ta.ema`, `ta.rsi`, `ta.macd`, `ta.pivotlow`/`ta.pivothigh`). Drop it on AAPL daily to verify against `data/port_check/aapl_signals.csv`. Added generator + endpoint tests.

**Mod-K (2026-06-06):** **Strategy profile named `hidden_div`; config dials mapped 1:1 to the Pine inputs.** Renamed the single strategy profile to `hidden_div` and aliased every `config.yaml` leaf key to its TradingView Pine input name (`wMacd`, `entryThreshold`, `lbR`, `minPivGap`, …) so the strategy can be exported to PineScript later — Python attribute names are unchanged, so the optimiser was untouched beyond a mechanical profile-name swap. Added `scripts/port_check_aapl.py`, which lists every BUY/SELL signal event (with component breakdown + entry/exit score) to `data/port_check/aapl_signals.csv` for eyeball comparison against the reference `.pine` on AAPL daily, plus an explicit **non-repaint pivot-lag** test (signal at `low + lbR`) and ≥3 unit tests each for hidden-bull divergence, regular-bear divergence, DeMark TD9 setup, DeMark TD13 countdown, and the regime gate.

**Mod-J (2026-06-06):** **Strategy replaced with Hidden-Divergence Confluence (long-only).** The previous 8-component composite scoring engine and the entire short-side (inverse-ETF) path were removed. The new engine enters on hidden bullish divergence (MACD/RSI) confirmed by a weighted entry-confluence score inside an EMA-50/200 uptrend regime, and exits on regular bearish divergence / DeMark TD exhaustion via a separate, lower-threshold exit score. New indicators: confirmed swing pivots, MACD/RSI divergence detection, and a simplified DeMark TD Sequential. The user can now tune each entry/exit component score, both thresholds, the confluence windows, and the underlying indicator parameters in Settings. Added **multiple watchlists** ("Watchlist", "Watchlist - ChinaTech", "Watchlist - 2", "Watchlist 3"), each editable and individually backtestable; all watchlists are part of the trading universe. The Optuna optimiser was reworked to search the new entry/exit score + threshold space (events are pre-computed once per symbol since they are weight-independent).

---

### v0.1.0 — May 2026

**Mod-I (May 2026):** Strategy optimiser with overfitting protection — Bayesian (Optuna TPE) parameter search, in-sample/holdout split, walk-forward validation, luck audit, perturbation stability test, and top-cluster check.

**Mod-G (May 2026):** Added "About" section with four tabs. Single source of truth in `docs/ABOUT.md`, rendered live via `GET /api/about`.

**Mod-F (May 2026):** Money-management overhaul — fixed-fractional position sizing, per-share platform fee model, ranked Top-N entry selection, buy-and-hold benchmark comparison (QQQ, total-return), extended metrics (CAGR, Sharpe, max drawdown, win rate, profit factor).

**Mod-D (May 2026):** Frontend navigation refactor — Dashboard, Settings, and Backtest as distinct top-level sections with sidebar nav.

**Mod-C (May 2026):** Market overview dashboard — live index tiles, sparkline charts, and CNN Fear & Greed gauge with a 15-minute server-side cache.

**Mod-A (May 2026):** Initial build. FastAPI backend; React + Vite + TypeScript frontend; yfinance price cache in Parquet; SQLite persistence for runs and signals; APScheduler for optional daily auto-scan.

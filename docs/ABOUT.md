# AlphaSignal — About

<!-- TAB_SPLIT -->
## Overview & Scope

AlphaSignal is a **personal-use** web application for analysing US equities and building/tuning a swing-trading strategy. It is **not** commercial software, **not** financial advice, and **not** designed for day trading. It operates on daily price bars and is intended for personal research only. The app runs a configurable universe of US stocks through an 8-component reversal/momentum scoring engine, lets the user tune weights and thresholds, and backtests the resulting strategy against historical data.

---

### Trading Universe

| Universe | Contents | Notes |
|----------|----------|-------|
| S&P 500 | Current S&P 500 members | Fetched from Wikipedia, cached locally |
| S&P MidCap 400 | Current S&P 400 members | Part of the "S&P 1000" |
| S&P SmallCap 600 | Current S&P 600 members | Part of the "S&P 1000" |
| Combined | S&P 500 ∪ MidCap 400 ∪ SmallCap 600 ∪ Watchlist, deduplicated | Default universe for scans |
| Watchlist | User-defined symbols (add/remove in Settings) | Always included in "combined" |

> **Note:** Universe lists reflect *current* index membership. Point-in-time membership (required to eliminate survivorship bias) is not tracked — see Backtest Details for implications.

---

### Data Sources

| Data | Source | Delay / Notes |
|------|--------|---------------|
| Daily OHLCV price bars (signal scanning) | yfinance / Yahoo Finance | Up to ~1 hour delay on recent bars; daily resolution only |
| Historical bars for backtesting | yfinance / Yahoo Finance | Adjusted total-return prices (dividends included via `auto_adjust=True`) |
| Market overview indices (^GSPC, ^DJI, ^NYA, ^IXIC, ^NDX, ^VIX, XLK, ^SP400, ^SP600) | yfinance fast_info | Cached 15 minutes in-process |
| CNN Fear & Greed Index | CNN dataviz API (`production.dataviz.cnn.io`) | Cached 15 minutes; undocumented endpoint with browser-like headers |
| Index constituent lists (S&P 500, 400, 600) | Wikipedia | Fetched once per session, cached as CSV files in `data/` |

---

### Architecture & Tech Stack

```
Browser
  └─ React 18 + Vite + TypeScript SPA
        ↕ HTTP (REST JSON)
Python FastAPI backend (port 8000)
  ├─ Signal engine  (pandas-ta indicators → 8-component composite score)
  ├─ Backtest engine  (walk-forward portfolio simulation)
  ├─ APScheduler  (optional daily auto-scan)
  └─ Storage
        ├─ SQLite  (runs, signals, watchlist, backtest results)
        └─ Parquet  (price bar cache, one file per symbol)
```

**Backend:** Python 3.11+, FastAPI, uvicorn, pandas, pandas-ta, numpy, yfinance, pydantic v2, PyYAML, SQLAlchemy/SQLite, pyarrow, httpx, APScheduler

**Frontend:** React 18, Vite, TypeScript, Tailwind CSS, lightweight-charts (TradingView-licensed chart component), TanStack Query, react-router-dom, SheetJS (xlsx export)

**Daily flow:** APScheduler (or manual trigger) → fetch/update Parquet price cache → compute 8-component score for each symbol → store Run + Signal rows in SQLite → frontend fetches on demand

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

AlphaSignal implements two complementary swing-trading strategies — **Long** (riding uptrends) and **Short** (profiting from downtrends via inverse ETFs). Both operate on daily bars.

---

### Long Strategy

Buy the underlying stock at **higher-low pullbacks** — retests of support within an established uptrend. Exit when the composite signal flips to bearish (indicating the pullback has ended or the trend has reversed).

- Signal computed on the stock itself using the **Long** scoring profile
- Trade executed on the stock directly (no leverage)
- Target: enter near swing-lows in an uptrend, exit near swing-highs

### Short Strategy

Profit from confirmed downtrends by **buying the corresponding single-stock inverse ETF** — not short-selling the stock. This avoids margin requirements and stock borrow costs.

- Signal computed on the **underlying stock** using the **Short** scoring profile (looks for bearish patterns)
- Trade executed on the **inverse ETF** (e.g. SQQQ for QQQ)
- Important caveat: single-stock inverse ETFs with daily-reset leverage accumulate **decay** on multi-day holds — real returns will diverge from a theoretical −1× underlying return

---

### Scoring System

Each of 8 components evaluates a different aspect of price action and returns a sub-score in **[−100, +100]**. The composite is the weighted average:

> **Composite = Σ (sub-score × weight/100)**, then regime gate applied

#### Component Weights (as configured in config.yaml)

| Component | Weight | What It Measures |
|-----------|:------:|-----------------|
| Candlestick | 12% | Single-bar pattern: hammer, engulfing, doji, spinning top |
| 3-Bar Pattern (p3) | 8% | 3-bar reversal/continuation patterns at S/R levels |
| 5-Bar Pattern (p5) | 12% | 5-bar swing structure: reversals, trend confirmation |
| Volume | 10% | Relative volume vs 30-day average (scaled to ±100) |
| EMA System | 15% | EMA-20/50/100/200 stacking order + recent crossovers |
| Support / Resistance | 15% | Proximity to identified S/R levels; bounces and breakouts |
| MACD | 18% | MACD golden/death cross, histogram direction, divergence |
| RSI | 10% | RSI zones (overbought/oversold) + 30/70 crossovers |
| **Total** | **100%** | |

*Weights are the same for Long and Short profiles by default.*

---

### Signal Thresholds (as configured in config.yaml)

| Signal | Long Profile | Short Profile |
|--------|:-----------:|:-------------:|
| Strong Buy | ≥ 60 | ≥ 85 |
| Buy | ≥ 50 | ≥ 70 |
| Hold | −50 to +50 | −70 to +70 |
| Sell | ≤ −50 | ≤ −70 |
| Strong Sell | ≤ −60 | ≤ −85 |

> The Short profile uses wider thresholds (±70/±85) to require a stronger bearish signal before acting, since inverse-ETF trades carry additional decay risk.

---

### Regime Gate (EMA-200)

Before any signal is actioned, the app checks the **market regime** for the individual stock using a 200-period EMA:

- **Bullish regime**: price is above EMA-200 AND the EMA-200 slope (over 20 bars) is rising → Long signals are allowed
- **Bearish regime**: price is below EMA-200 AND the EMA-200 slope is falling → Short signals are allowed
- If neither regime is confirmed, neither Long nor Short signals are generated for that stock

This ensures the app **never trades against the prevailing trend** on the individual stock level.

---

### Strategy Limitations

- **Daily timeframe only** — not predictive of intraday moves; cannot react to news within the trading day
- **Whipsaw risk** in choppy/range-bound markets where neither trend is confirmed; the EMA-200 gate reduces but does not eliminate this
- **Inverse-ETF decay** on multi-day holds — the longer the hold, the more the real ETF return diverges from −1× the underlying
- **Weights and thresholds are user-tuned** — they can overfit to the backtest period used to calibrate them
- **No fundamental awareness** — earnings surprises, guidance changes, and macro events are not in the model (only the optional earnings blackout is available)
- **EMA-200 regime lags** true trend reversals by design; a regime flip will not occur on the first day of a new trend

<!-- TAB_SPLIT -->
## Backtest Details & Limitations

The backtest engine simulates a walk-forward portfolio — it processes each trading day in sequence, using only information available up to that close, and fills orders at the *next* day's open.

---

### How the Backtest Works

#### Signal & Fill Timing (no look-ahead)

> Signal for bar **T** uses only data from bars 0 … T (no future data).
> Entry and exit orders fill at bar **T+1's open price.**

#### Portfolio Simulation

| Parameter | Default (as configured in config.yaml) |
|-----------|:---:|
| Starting capital | $100,000 |
| Position sizing | 8% of current equity per position |
| Minimum position size | $2,000 |
| Per-name capital cap | 30% of equity |
| Max concurrent open positions | 15 |
| Top-N candidates selected per day | 10 (ranked by composite score) |
| ATR stop multiple | 1.5× 14-period ATR |
| Trailing stop | Yes — moves in the favourable direction using today's close |
| Re-entry cooldown after stop-out | 5 bars |

**Entry selection:** On each day, all new Buy/Strong Buy signals (Long) or Sell/Strong Sell signals (Short) are ranked by composite score. Only the top 10 candidates proceed to the slot-and-capital check, then fill at tomorrow's open.

**Exits:**
- **ATR stop** hit intrabar (checked against daily high/low) → fills at stop price or open if gapped through
- **Opposite signal** on a held position → fills at next day's open
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

### Backtest Limitations

- **Data delay & granularity:** Daily bars only; yfinance data may be delayed up to ~1 hour. Not suitable for same-day decision-making or intraday timing.

- **Lookback limit:** Default 5-year lookback. Indicators requiring warm-up (e.g., EMA-200 needs 200 bars) reduce effective trade history in the first few months. yfinance provides 20+ years for most large-cap stocks.

- **Short-side history constraint:** Single-stock inverse ETFs were mostly launched after 2022. Most names have only 1–3 years of inverse-ETF history, limiting the meaningful window for short-side backtests. The app reports a coverage summary showing which names were testable and the date range.

- **SURVIVORSHIP BIAS (important):**
  The S&P 500, MidCap 400, and SmallCap 600 universe lists reflect *current* membership — companies as they exist today. Companies that were **delisted, went bankrupt, or were removed from the index** during the backtest period are absent from the test.
  
  **Example:** Backtesting "the S&P 500 over 5 years" using today's 500 members only tests companies that *survived and stayed in* the index for the full 5 years. Companies that dropped out (often because they declined significantly) are excluded. This makes the backtest results look better than they would have been in real time — a "fake-good" upward bias.
  
  Correcting this requires point-in-time index membership data (not available for free). Treat all backtest returns as an **optimistic upper bound**.

- **Inverse-ETF decay overstates short gains:** Single-stock inverse ETFs reset leverage daily. Over multi-day holds, the ETF underperforms (and overstates losses relative to) a theoretical −1× underlying return. The backtest uses real ETF P&L where history exists, but the limited ETF history means many short-side signals from the underlying's longer history cannot be backtested.

- **No liquidity or market-impact modelling:** Thin small-cap stocks may have wide bid/ask spreads. The 0.1% slippage assumption may be optimistic for illiquid names.

- **No borrow cost or tax modelling.**

- **Corporate actions** are handled only via adjusted prices. Mergers, spin-offs, and symbol changes may cause data gaps or discontinuities.

- **Past performance does not predict future results. This backtest is for personal research and strategy understanding only — not investment advice.**

<!-- TAB_SPLIT -->
## Changelog

Entries are reverse-chronological (most recent first). Each mod corresponds to a development phase.

---

### v0.1.0 — May 2026

**Mod-G (May 2026):** Added "About" section with four tabs (Overview & Scope, Strategy Details, Backtest Details & Limitations, Changelog). Single source of truth in `docs/ABOUT.md`, rendered live via `GET /api/about`. Added standing rule to CLAUDE.md to keep this document current.

**Mod-F (May 2026):** Money management overhaul — fixed-fractional position sizing (8% equity, $2,000 floor), per-share platform fee model ($0.005/share, min $1, max 1% of trade), ranked Top-N entry selection (best 10 candidates per day by composite score), buy-and-hold benchmark comparison (QQQ, total-return), extended metrics (CAGR, Sharpe ratio, max drawdown, win rate, profit factor).

**Mod-E (May 2026):** Short-side backtest — computes SHORT profile signals on the underlying stock, then trades the actual single-stock inverse ETF. Coverage report shows which names are testable, what ETF history window is available, and how many signals were skipped before ETF launch. Survivorship bias note added to engine output.

**Mod-D (May 2026):** Frontend navigation refactor — Dashboard, Settings, and Backtest as distinct top-level sections with sidebar nav. React Router integrated.

**Mod-C (May 2026):** Market overview dashboard — live index tiles for S&P 500, Dow Jones, NYSE, NASDAQ Composite, NASDAQ 100, VIX, Tech Sector (XLK), MidCap 400, SmallCap 600 (all via yfinance), sparkline charts, and CNN Fear & Greed gauge. 15-minute server-side cache.

**Mod-B (May 2026):** Separate LONG and SHORT scoring configuration profiles in `config.yaml`. EMA-200 regime gate — bullish regime gates long signals, bearish regime gates short signals. All weights and thresholds configurable per profile.

**Mod-A (May 2026):** Initial build. FastAPI backend with uvicorn; React + Vite + TypeScript frontend; yfinance price cache in Parquet; 8-component composite scoring engine (candlestick, p3, p5, volume, EMA system, support/resistance, MACD, RSI); SQLite persistence for runs and signals; APScheduler for optional daily auto-scan; Settings page for weight tuning and strategy thresholds.

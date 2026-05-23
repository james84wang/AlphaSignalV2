# AlphaSignal API Contract — v1

Base URL: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs`

All timestamps are ISO 8601 UTC. All dates are `YYYY-MM-DD` strings.

---

## GET /health
Health check. Returns 200 if the server is up.

**Response 200**
```json
{
  "status": "ok",
  "app": "AlphaSignal",
  "version": "0.1.0",
  "weights_valid": true
}
```

---

## GET /api/signals

Return a ranked signal table from the most recent daily run matching the filters.

**Query parameters**

| Param     | Type   | Default      | Description |
|-----------|--------|--------------|-------------|
| `date`    | string | latest avail | `YYYY-MM-DD` — filter to runs whose signals cover this date |
| `universe`| string | `watchlist`  | `watchlist`, `sp500`, or `combined` |

**Response 200**
```json
{
  "run_id": 7,
  "run_timestamp": "2025-01-15T18:30:00+00:00",
  "date": "2025-01-15",
  "universe": "watchlist",
  "config_hash": "a3f2bc19d4e71234",
  "n_signals": 12,
  "signals": [
    {
      "rank": 1,
      "symbol": "AAPL",
      "composite": 78.4,
      "signal": "Buy",
      "long_allowed": true,
      "short_allowed": false,
      "sub_scores": {
        "candlestick": 90.0,
        "p3": 0.0,
        "p5": 50.0,
        "volume": 60.0,
        "ema": 80.0,
        "sr": 75.0,
        "macd": 55.0,
        "rsi": 65.0
      }
    }
  ]
}
```

**Response 404** — no runs found for the given filters.

---

## GET /api/symbols/{symbol}/bars

Return OHLCV bars in lightweight-charts compatible format.

**Path parameters**

| Param    | Type   | Description |
|----------|--------|-------------|
| `symbol` | string | Ticker, e.g. `AAPL` |

**Query parameters**

| Param   | Type   | Default | Values                          |
|---------|--------|---------|---------------------------------|
| `range` | string | `1y`    | `1m`, `3m`, `6m`, `1y`, `2y`, `5y` |

**Response 200**
```json
{
  "symbol": "AAPL",
  "range": "1y",
  "start": "2024-01-15",
  "end": "2025-01-15",
  "n_bars": 252,
  "bars": [
    {
      "time": "2024-01-16",
      "open": 182.16,
      "high": 184.12,
      "low": 181.50,
      "close": 183.63,
      "volume": 65234100
    }
  ]
}
```

**Response 404** — no data for symbol.

---

## GET /api/symbols/{symbol}/signal

Return the full audit object (all sub-scores and weights) for a symbol on a given date.
Tries the DB first; recomputes on-the-fly if not persisted.

**Path parameters**

| Param    | Type   | Description |
|----------|--------|-------------|
| `symbol` | string | Ticker, e.g. `AAPL` |

**Query parameters**

| Param  | Type   | Default | Description |
|--------|--------|---------|-------------|
| `date` | string | today   | `YYYY-MM-DD` |

**Response 200**
```json
{
  "symbol": "AAPL",
  "date": "2025-01-15",
  "composite": 78.4,
  "signal": "Buy",
  "source": "db",
  "regime": {
    "long_allowed": true,
    "short_allowed": false
  },
  "components": {
    "candlestick": { "sub": 90.0, "weight": 12.0, "weighted": 10.8 },
    "p3":          { "sub": 0.0,  "weight": 8.0,  "weighted": 0.0 },
    "p5":          { "sub": 50.0, "weight": 12.0, "weighted": 6.0 },
    "volume":      { "sub": 60.0, "weight": 10.0, "weighted": 6.0 },
    "ema":         { "sub": 80.0, "weight": 15.0, "weighted": 12.0 },
    "sr":          { "sub": 75.0, "weight": 15.0, "weighted": 11.25 },
    "macd":        { "sub": 55.0, "weight": 18.0, "weighted": 9.9 },
    "rsi":         { "sub": 65.0, "weight": 10.0, "weighted": 6.5 }
  }
}
```

`source` is `"db"` when returned from the database, `"computed"` when recomputed on-the-fly.

**Response 404** — symbol not found or no data for date.

---

## GET /api/config/{strategy}

Return the configuration for a specific strategy profile (`long` or `short`).

**Path parameters**

| Param      | Type   | Values         |
|------------|--------|----------------|
| `strategy` | string | `long`, `short` |

**Response 200** — the strategy profile as a JSON object:
```json
{
  "thresholds": {
    "strong_buy": 85,
    "buy": 70,
    "sell": -70,
    "strong_sell": -85
  },
  "weights": {
    "candlestick": 12,
    "p3": 8,
    "p5": 12,
    "volume": 10,
    "ema": 15,
    "sr": 15,
    "macd": 18,
    "rsi": 10
  },
  "regime": { "ema_period": 200, "slope_lookback": 20 },
  "...": "all other scoring tables for this profile"
}
```

**Response 422** — invalid strategy name.

---

## PUT /api/config/{strategy}

Update component weights for one strategy profile. Validates that all 8 weights sum to 100. Persists a versioned snapshot.

**Path parameters**

| Param      | Type   | Values         |
|------------|--------|----------------|
| `strategy` | string | `long`, `short` |

**Request body**
```json
{
  "candlestick": 12,
  "p3": 8,
  "p5": 12,
  "volume": 10,
  "ema": 15,
  "sr": 15,
  "macd": 18,
  "rsi": 10
}
```

All 8 fields are required. Values must be non-negative and sum to exactly 100.

**Response 200**
```json
{
  "ok": true,
  "strategy": "long",
  "weights": { "candlestick": 12, "p3": 8, "...": "..." },
  "config_hash": "new_hash_here",
  "version_saved_at": "2025-01-15T18:30:00+00:00"
}
```

**Response 422** — weights do not sum to 100, or a field is missing/negative.

---

## GET /api/watchlist

Return the current watchlist (stored in SQLite, seeded once from `data/watchlist.csv`).

**Response 200**
```json
{
  "count": 3,
  "symbols": [
    { "symbol": "AAPL", "added_at": "2025-01-15T18:00:00+00:00", "note": null },
    { "symbol": "MSFT", "added_at": "2025-01-15T18:00:00+00:00", "note": "AI play" }
  ]
}
```

---

## POST /api/watchlist

Add a symbol to the watchlist.

**Request body**
```json
{ "symbol": "NVDA", "note": "optional free text" }
```

`symbol` is validated (1–10 uppercase alphanumeric chars). `note` is optional.

**Response 201**
```json
{ "symbol": "NVDA", "added_at": "2025-01-15T18:30:00+00:00", "note": null }
```

**Response 409** — symbol already in watchlist.
**Response 422** — invalid symbol format.

---

## DELETE /api/watchlist/{symbol}

Remove a symbol from the watchlist.

**Response 200**
```json
{ "ok": true, "symbol": "NVDA" }
```

**Response 404** — symbol not in watchlist.

---

## GET /api/inverse-etfs

Return the current inverse-ETF map (loaded from `data/inverse_etfs.csv`).

**Response 200**
```json
{
  "count": 4,
  "map": {
    "SPY": { "inverse_etf_symbol": "SH", "leverage": -1, "note": "ProShares Short S&P500" },
    "QQQ": { "inverse_etf_symbol": "PSQ", "leverage": -1, "note": "ProShares Short QQQ" },
    "DIA": { "inverse_etf_symbol": "DOG", "leverage": -1, "note": "ProShares Short Dow30" },
    "IWM": { "inverse_etf_symbol": "RWM", "leverage": -1, "note": "ProShares Short Russell 2000" }
  }
}
```

To add single-stock inverse ETFs, edit `data/inverse_etfs.csv` directly
(columns: `underlying_symbol,inverse_etf_symbol,leverage,note`).

---

## POST /api/runs/daily

Trigger a daily signal run in the background.

**Request body**
```json
{
  "universe": "combined",
  "strategy": "long",
  "date": "2025-01-15"
}
```

`universe` defaults to `"combined"`. Valid values: `"watchlist"`, `"sp500"`, `"combined"`.
`"combined"` = S&P 500 ∪ S&P 1000 (MidCap 400 + SmallCap 600) ∪ watchlist, de-duplicated.
`strategy` defaults to `"long"` (`"long"` or `"short"`). `date` defaults to today.

Short-strategy signals include an `inverse_etf` field on each signal row: the mapped
inverse-ETF symbol if one exists in `data/inverse_etfs.csv`, otherwise `null` (signal
is still emitted; `no_inverse_etf` flag is set to `true`).

**Response 202**
```json
{
  "job_id": "a3f2bc19",
  "status": "running",
  "message": "Daily run started for universe=combined strategy=long date=2025-01-15"
}
```

---

## GET /api/runs/daily/{job_id}

Poll the status of a daily run job.

**Response 200 — running**
```json
{
  "job_id": "a3f2bc19",
  "status": "running",
  "started_at": "2025-01-15T18:30:00+00:00"
}
```

**Response 200 — done**
```json
{
  "job_id": "a3f2bc19",
  "status": "done",
  "started_at": "2025-01-15T18:30:00+00:00",
  "finished_at": "2025-01-15T18:32:15+00:00",
  "run_id": 8,
  "n_success": 12,
  "n_errors": 0,
  "universe": "combined",
  "strategy": "long",
  "date": "2025-01-15"
}
```

**Response 200 — error**
```json
{
  "job_id": "a3f2bc19",
  "status": "error",
  "started_at": "2025-01-15T18:30:00+00:00",
  "finished_at": "2025-01-15T18:30:05+00:00",
  "error": "No symbols found in watchlist"
}
```

**Response 404** — unknown job_id.

---

## POST /api/backtest

Start a backtest run in the background.

**Request body**
```json
{
  "universe": "watchlist",
  "symbols": ["AAPL", "MSFT"],
  "start": "2020-01-01",
  "end": "2025-01-01",
  "initial_account": 100000,
  "slippage_pct": 0.001,
  "commission": 1.0,
  "strategy": "long"
}
```

`universe` and `symbols` are mutually exclusive; if `universe` is given, symbols are loaded from it.
`start` and `end` default to `cfg.backtest.start_years_back` years ago → today.
`initial_account`, `slippage_pct`, `commission` fall back to config defaults.
`strategy` is `"long"` (default) or `"short"`. For `"short"`, the signal is computed on the
underlying using the short profile, but the **trade** fills on the real inverse ETF from
`data/inverse_etfs.csv`. Names with no mapped inverse ETF are reported under
`coverage_report.skipped_no_instrument` and are NOT included in headline metrics.

**Response 202**
```json
{
  "job_id": "d8e2f1a4",
  "status": "running",
  "message": "Backtest started: watchlist 2020-01-01 → 2025-01-01 strategy=long"
}
```

---

## GET /api/backtest/{job_id}

Poll status or retrieve the full result of a backtest job.

**Response 200 — running**
```json
{
  "job_id": "d8e2f1a4",
  "status": "running",
  "started_at": "2025-01-15T18:30:00+00:00"
}
```

**Response 200 — done**
```json
{
  "job_id": "d8e2f1a4",
  "status": "done",
  "db_run_id": 3,
  "strategy": "long",
  "started_at": "2025-01-15T18:30:00+00:00",
  "finished_at": "2025-01-15T18:35:00+00:00",
  "duration_seconds": 300.4,
  "params": {
    "strategy": "long",
    "start": "2020-01-01",
    "end": "2025-01-01",
    "symbols": ["AAPL", "MSFT"],
    "n_symbols_loaded": 2,
    "initial_account": 100000
  },
  "metrics": {
    "n_trades": 47,
    "hit_rate": 0.55,
    "avg_win": 1240.50,
    "avg_loss": -680.25,
    "profit_factor": 1.82,
    "max_drawdown_pct": 14.3,
    "sharpe": 1.24,
    "cagr": 18.6,
    "total_return_pct": 134.2,
    "final_equity": 234200.0,
    "exposure_pct": 42.1
  },
  "equity_curve": [
    { "date": "2020-01-02", "equity": 100000.0, "n_open": 0 }
  ],
  "trades": [
    {
      "symbol": "AAPL",
      "side": "long",
      "entry_date": "2020-01-06",
      "entry_price": 300.35,
      "exit_date": "2020-01-20",
      "exit_price": 318.73,
      "shares": 33.2,
      "initial_stop": 294.10,
      "pnl": 610.50,
      "pnl_pct": 6.12,
      "exit_reason": "signal",
      "underlying_symbol": null,
      "trade_instrument": null,
      "synthetic_pnl": null,
      "synthetic_pnl_pct": null
    }
  ],
  "survivorship_note": "SURVIVORSHIP BIAS WARNING: ...",
  "coverage_report": null
}
```

For `strategy="short"` runs, `coverage_report` is populated:

```json
{
  "coverage_report": {
    "tested": [
      {
        "underlying": "SPY",
        "inverse_etf": "SH",
        "window_tested_start": "2006-06-19",
        "window_tested_end": "2025-01-15",
        "n_trades": 12,
        "skipped_signals_before_etf_launch": 0
      }
    ],
    "skipped_no_instrument": ["AAPL", "MSFT"],
    "skipped_insufficient_history": [
      { "underlying": "IWM", "inverse_etf": "RWM", "reason": "only 30 overlapping bars (need ≥ 50)" }
    ],
    "skipped_data_error": [],
    "summary": {
      "universe_size": 4,
      "n_testable": 1,
      "pct_testable": 25.0,
      "avg_tested_window_days": 6780
    }
  }
}
```

Short trades also carry decay-diagnostic fields:

```json
{
  "symbol": "SH",
  "underlying_symbol": "SPY",
  "trade_instrument": "SH",
  "pnl": 320.50,
  "pnl_pct": 3.2,
  "synthetic_pnl": 450.20,
  "synthetic_pnl_pct": 4.5,
  "...": "..."
}
```

`synthetic_pnl` is what the trade would have returned if we had simply inverted the
underlying's return (−1× the underlying's price change over the same trade window).
Comparing `pnl` vs `synthetic_pnl` shows the inverse-ETF decay drag.

**Response 200 — error**
```json
{
  "job_id": "d8e2f1a4",
  "status": "error",
  "error": "No symbols loaded — aborting backtest"
}
```

**Response 404** — unknown job_id.

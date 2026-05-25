# Shared Changes Requests

This file tracks requested changes to shared files (config.yaml, pyproject.toml, CLAUDE.md)
that individual phase sessions cannot edit directly.

---

## Phase 3 → universe.py path bug

**File:** `backend/app/data/universe.py`

**Issue:** `_REPO_ROOT = Path(__file__).resolve().parents[4]` resolves one level too high
(`Claude/Code/` instead of `AlphaSignalV2/`), so the default watchlist path is
`Claude/Code/data/watchlist.csv` rather than `AlphaSignalV2/data/watchlist.csv`.

**Fix:** Change `parents[4]` → `parents[3]` on lines 19–20 of `universe.py`.

**Workaround in place:** `scripts/run_daily.py` passes `watchlist_path=_WATCHLIST_PATH`
explicitly so Phase 3 is unaffected. But the bug will surface if anyone calls
`Universe()` without an explicit path.

---

## MOD-D → Backend contract gaps (frontend needs these)

### 1. GET /api/signals — add `strategy` query param

**Problem:** The dashboard shows two separate sections (long signals / short signals). Currently
`GET /api/signals` has no strategy filter, so it returns results from whichever run happened last.
With two independent "Run Long" / "Run Short" buttons the user may have both sets persisted in the
DB but can only retrieve one at a time.

**Requested change:** Add `strategy` query param (`long` | `short`) to `GET /api/signals` so the
frontend can request the latest long-run results and the latest short-run results independently.

**Frontend workaround in place:** The UI filters client-side (Buy/Strong Buy = long section;
Sell/Strong Sell = short section). Works for a single combined run but will be stale if the user
runs long and short at different times.

---

### 2. GET /api/signals — short signals should carry `inverse_etf` field

**Problem:** The short-signals section in the dashboard needs to show an "Inverse ETF to buy"
column per signal row. The `POST /api/runs/daily` response mentions an `inverse_etf` field on
short-signal rows, but `GET /api/signals` doesn't return it.

**Requested change:** Persist and return `inverse_etf` (string or null) and `no_inverse_etf`
(bool) on each signal row in `GET /api/signals`, at least when the run strategy was `"short"`.

**Frontend workaround in place:** The UI fetches `GET /api/inverse-etfs` and looks up the mapping
client-side by underlying symbol. Accurate as long as the CSV is up to date.

---

### 3. PUT/POST /api/inverse-etfs — inverse-ETF map editor

**Problem:** The settings page has an inverse-ETF map editor. `GET /api/inverse-etfs` is
implemented, but there is no write endpoint.

**Requested change:** Add `PUT /api/inverse-etfs` (or `POST` + `DELETE`) so the user can add,
edit, and remove rows without touching the CSV directly.

**Frontend workaround in place:** The editor shows the current map read-only with a notice
directing the user to edit `data/inverse_etfs.csv` and restart.

---

### 4. PUT /api/config/{strategy} — extend to accept thresholds and scoring-table overrides

**Problem:** The settings page exposes editable thresholds (strong_buy, buy, sell, strong_sell)
and per-pattern scoring tables. The current PUT body only accepts the 8 component weights.

**Requested change:** Expand the PUT body (and backend validation) to also accept optional
`thresholds` and per-table score overrides, persisting them in the same versioned snapshot.

**Frontend workaround in place:** Thresholds and scoring tables are displayed read-only with a
note that editing requires the expanded PUT endpoint.

---

## MOD-F → Backtest page: new fields from portfolio engine

The `GET /api/backtest/{job_id}` done response now includes MOD-F fields. The frontend
`Backtest.tsx` should be updated to consume them:

### New top-level response fields
- `strategy_metrics` — full MOD-F metric set (replaces bare `metrics` for display).
  New keys: `win_rate`, `win_loss_ratio`, `turnover`, `avg_holding_days`, `total_fees`,
  `sharpe_ratio` (alias `sharpe`), `max_drawdown` (alias `max_drawdown_pct`).
- `benchmark_metrics` — 5-metric set: `total_return`, `cagr`, `sharpe_ratio`, `max_drawdown`, `final_equity`.
- `comparison` — side-by-side table: `{ metrics: { total_return: { strategy, benchmark }, ... }, fairness_caveat, sharpe_convention, price_basis }`.
- `benchmark_equity_curve` — `[{date, equity, n_open}, ...]` for QQQ buy-and-hold overlay.
- `constraint_counts` — `{ skipped_no_slot, skipped_no_capital, skipped_top_n }`.

### Updated trade fields
Each trade in `trades[]` now has `entry_fee` and `exit_fee` (float, USD).

### Updated params fields
`params.initial_fund` (was `initial_account`), plus new keys: `position_size_pct`,
`position_size_min`, `fee_per_share`, `fee_min`, `fee_max_pct_of_trade`, `atr_stop_multiple`,
`atr_period`, `max_concurrent_positions`, `per_name_cap_pct`, `top_n`,
`benchmark_symbol`, `risk_free_rate`, `price_basis`.

### Recommended UI additions
1. **Strategy vs Benchmark table** — render `comparison.metrics` as a 3-column table
   (Metric | Strategy | Benchmark). Add `fairness_caveat` as a footnote.
2. **Benchmark equity curve overlay** — plot `benchmark_equity_curve` as a second line
   on the equity chart (grey line labelled "QQQ buy-and-hold").
3. **Extended metrics panel** — add `turnover`, `avg_holding_days`, `total_fees`,
   `win_loss_ratio` alongside the existing metrics display.
4. **Constraint counts chip** — show `constraint_counts` as a small info badge:
   "Skipped: N slot / M capital / K ranked-out".

# MOD-E — Per-profile backtest (long on underlying, short on real inverse ETF) + coverage report

> Depends only on mod-a (profiles) and mod-b (inverse-ETF mapping). RECOMMENDED ORDER:
> run this right after mod-b, before mod-c/mod-d — validate the strategy before polishing UI.
> In Claude Code:  `Read prompts/mod-e.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md, API_CONTRACT.md, spec §6.5, and the existing backend/app/backtest/ code.
Run `git commit -m "checkpoint before mod-e"` and `pytest -q` first. STOP if baseline
tests fail.

GOAL
Extend the existing single-strategy backtester into a PER-PROFILE backtester that is
honest about the long/short asymmetry:
- LONG profile: signal AND trade are on the underlying stock.
- SHORT profile: signal is computed on the underlying stock, but the trade is simulated on
  the ACTUAL inverse ETF price series (from data/inverse_etfs.csv) — NOT by inverting the
  stock. This is to capture real inverse-ETF decay/tracking error over multi-day swings.
- For any name that cannot be honestly tested on the short side, produce a CLEAR report
  rather than skipping silently or faking a result.

WHY (do not shortcut this)
Inverse ETFs reset daily, so over multi-day holds their return drifts from the underlying's
inverse. Backtesting the short side by inverting the stock OVERSTATES results. We test on
the real ETF series so the numbers reflect what I'd actually experience.

BUILD
1. Make the backtest engine PROFILE-AWARE: backtest(strategy="long"|"short", universe,
   start, end). Reuse the existing walk-forward loop, metrics, and money-management code.
   All risk params (1.5×ATR stop, 2% risk sizing, max 10 positions, 5-bar cooldown,
   slippage, commission) continue to come from config.yaml.

2. LONG backtest:
   - Signal from the LONG profile on the underlying; enter on T+1 open of the underlying;
     manage stop/size/exit on the underlying. (Essentially the existing behaviour, now
     explicitly using the long profile.)

3. SHORT backtest (the new, careful path):
   - For each underlying, compute the SHORT-profile signal on the underlying (regime gate
     for short applies) using ONLY data up to and including bar T.
   - Look up the inverse ETF from the mapping. The TRADE is: buy the inverse ETF at its
     T+1 open; exit when the underlying produces an opposite signal OR the inverse-ETF
     trailing stop is hit. IMPORTANT: compute the stop (1.5×ATR) and the 2% position size
     on the INVERSE ETF's own price/ATR (that's the instrument I hold and risk), while the
     ENTRY/EXIT TRIGGERS come from the underlying's signals.
   - All P&L is measured on the inverse ETF's real price series. Align dates on the shared
     US trading calendar; never use a future bar of either series (no look-ahead).

4. DECAY DIAGNOSTIC (recommended, high value):
   - For each short name actually tested, ALSO compute a "naive synthetic short" (inverting
     the underlying's return over the same trades/window) and report both side by side, so
     the inverse-ETF decay drag is visible as a number (real_return vs synthetic_return).

5. COVERAGE / UNTESTABLE REPORT (first-class output, not a log line). For a short backtest
   over a universe, return structured buckets:
   - tested: [{underlying, inverse_etf, window_tested_start, window_tested_end,
              n_trades, skipped_signals_before_etf_launch}]   # partial history = still tested, window flagged
   - skipped_no_instrument:        [underlyings with no inverse ETF mapping]
   - skipped_insufficient_history: [{underlying, inverse_etf, reason}]  # ETF exists but no usable overlap
   - skipped_data_error:           [{symbol, error}]
   - summary: { universe_size, n_testable, pct_testable, avg_tested_window_days }
   Print a human-readable version too (e.g. "Asked to test 1000 names; 23 testable;
   avg usable window 1.8 yrs; 977 had no inverse ETF").

6. PERSISTENCE & API:
   - Persist each backtest run with: profile, params, config hash, metrics, equity curve,
     trade log, and (for short runs) the coverage report.
   - API: POST /api/backtest {strategy, universe, start, end} -> run id;
     GET /api/backtest/{id} -> status + metrics + equity curve + trades + coverage report.
   - Update API_CONTRACT.md. (Wiring this into the existing backtest UI screen is optional;
     if you add anything the frontend needs, note it in SHARED_CHANGES.md — don't redesign
     the frontend here.)

ANTI-LOOK-AHEAD (write/keep these tests)
- signal(T) on the underlying is unchanged whether or not bars > T exist.
- Inverse-ETF entries fill on T+1 open; stops/exits use the ETF's intrabar high/low; no
  future ETF bar leaks into a past decision.
- A short trade is only opened on dates where BOTH the underlying signal and the inverse
  ETF price exist.

HONEST CAVEATS TO SURFACE IN THE REPORT
- Single-stock inverse ETFs are recent → short-side history is short and the testable
  universe is small. State the realistic coverage plainly.
- Thin inverse ETFs have wider spreads and higher expense ratios; the default slippage may
  be optimistic for them. Note this.
- Survivorship: current-membership universe only (already flagged elsewhere).

ACCEPTANCE
- One command backtests the LONG profile over the universe and returns metrics + equity
  curve + trade log.
- One command backtests the SHORT profile and returns the same PLUS the coverage report,
  with at least one mapped name (e.g. SPY→SH) actually tested on real ETF data.
- Changing a weight/threshold in a profile changes that profile's backtest result.
- For a name with no inverse ETF, the short backtest reports it under
  skipped_no_instrument and does NOT fabricate a synthetic result in the headline metrics.

MANUAL STEPS FOR JAMES
Show me the exact commands to: (1) backtest the long profile over the combined universe,
(2) backtest the short profile over the combined universe, and (3) read the coverage report.
Tell me, in plain English, what % of my universe is actually testable on the short side and
the average usable history length.

REPORT BACK
Show the long-profile metrics, the short-profile metrics, the decay diagnostic for a couple
of tested names (real vs synthetic), and the coverage summary. Tell me honestly whether the
short side has enough testable history to draw any conclusion yet. Then `git commit`.
```

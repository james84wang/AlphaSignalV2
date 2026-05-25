# MOD-F — Backtest money management, fees, ranked selection, benchmark & metrics

> Depends on mod-e (the per-profile backtest engine). Run AFTER mod-e. Run mod-c/mod-d
> whenever; this is independent of them.
> In Claude Code:  `Read prompts/mod-f.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md, API_CONTRACT.md, and the existing backend/app/backtest/ code (engine.py,
metrics.py) plus the mod-e per-profile changes. Run `git commit -m "checkpoint before mod-f"`
and `pytest -q` first. STOP if baseline tests fail.

GOAL
Upgrade the backtester from simple per-trade simulation into a realistic PORTFOLIO-level
simulation with proper fees, capital allocation, ranked daily selection, a buy-and-hold
benchmark, and a richer, apples-to-apples metrics set. All new numbers live in config.yaml.

SCOPE NOTE — per profile, one portfolio
Each backtest run simulates ONE strategy profile (long OR short) as a single portfolio
with one cash balance and the slots below. (Long trades the underlying; short trades the
real inverse ETF, per mod-e.) Do NOT merge long+short into one combined book in this phase
— that's a future option. The benchmark is the same for both so they're comparable.

--------------------------------------------------------------------
PART 1 — EXECUTION TIMING (confirm / enforce; likely already true from mod-e)
--------------------------------------------------------------------
- Signals are computed on the CLOSE of bar T using ONLY data through bar T.
- Entries and exits FILL at the next bar's OPEN (T+1 open). Never fill at T's close.
- Keep/extend the existing anti-look-ahead tests proving signal(T) is unchanged whether or
  not bars > T exist, and that fills use T+1 open.

--------------------------------------------------------------------
PART 2 — NEW BACKTEST PARAMETERS (all in config.yaml under a `backtest:` section)
--------------------------------------------------------------------
Add these with the stated defaults. Every one must be overridable via config and via the
POST /api/backtest request body.

1. Platform fee (per side — charged on BOTH entry and exit):
     fee_per_share        = 0.005   ($/share)
     fee_min              = 1.00     ($ per trade)
     fee_max_pct_of_trade = 0.01     (1% of trade value)
   Formula per fill: fee = clamp(shares * fee_per_share, fee_min, fee_max_pct_of_trade *
   shares * fill_price). Apply on entry fill and again on exit fill. Deduct from cash.

2. Initial fund:
     initial_fund = 100000

3. Position sizing (fixed-fractional on CURRENT EQUITY — THIS REPLACES the old
   2%-risk/ATR sizing):
     position_size_pct = 0.08        (8% of current equity)
     position_size_min = 2000        ($ floor per position)
     sizing_base       = current_equity   # default; option: initial_fund
   Target position $ = position_size_pct * current equity (it compounds as equity grows/
   shrinks). If target < position_size_min, use position_size_min. If available cash < the
   required amount, SKIP the trade (do not take an undersized position).

4. ATR stop loss (governs EXITS; sizing is separate, see #3):
     atr_stop_multiple = 1.5
     atr_period        = 14
   Exit a position when price hits entry ∓ atr_stop_multiple × ATR(atr_period) (below entry
   for longs / the inverse-ETF long, per mod-e). This is the trailing/initial stop; keep the
   existing "exit on opposite signal" rule too — whichever triggers first.

5. Max concurrent positions:
     max_concurrent_positions = 15

6. Per-name cap (entry guardrail):
     per_name_cap_pct = 0.30         (a single position's entry value ≤ 30% of equity)
   At 8% sizing this rarely binds; keep it as a hard guard and skip/clip any entry that
   would exceed it. (Base it on current equity, consistent with sizing.)

7. Ranked selection:
     top_n = 10
   Each bar, AFTER computing exits, determine open slots = max_concurrent_positions − held.
   Build the candidate list = all symbols generating a fresh entry signal that also pass
   the regime gate and the 5-bar cooldown. Rank candidates by composite score (strongest
   first — most positive for long, most negative for short). Walk down the top_n ranked
   candidates and open positions until: slots are full, OR cash can't fund another position
   (≥ position_size_min), OR top_n candidates exhausted. Record which candidates were
   skipped due to "no slot" vs "no capital" so I can see if I'm capital- or slot-constrained.
   NOTE: top_n (10) caps NEW entries PER BAR; max_concurrent (15) caps TOTAL held. With
   top_n < max_concurrent you fill the extra slots over multiple bars as signals persist —
   this is intended, not a bug.

8. Benchmark:
     benchmark_symbol = "QQQ"
   Simulate buying the benchmark with the ENTIRE initial_fund at the start-date T+1 open
   (apply ONE entry fee), holding to the end date, and marking to market. No rebalancing,
   no exit fee (still held at end). Compute its return on an ADJUSTED / TOTAL-RETURN basis
   so dividends are included. Run this for every backtest so each run has its benchmark
   alongside.

DIVIDEND / PRICE BASIS (consistency matters):
Use adjusted / total-return prices (dividends included) for BOTH the strategy instruments
AND the benchmark, so dividends are treated the same way on both sides. State clearly in the
output which basis you used. Do not mix price-only on one side and total-return on the other.

CASH: un-deployed cash earns the risk-free rate (default 0). Note this affects Sharpe.

--------------------------------------------------------------------
PART 3 — METRICS (metrics.py)
--------------------------------------------------------------------
Compute for the STRATEGY portfolio:
  - total_return, CAGR, sharpe_ratio, max_drawdown, final_equity   (SAME 5 as benchmark)
  - win_rate, avg_win, avg_loss, win_loss_ratio (avg_win / |avg_loss|), profit_factor
  - turnover: annualized = (sum of absolute $ traded over the period) / (average equity),
    scaled to a yearly figure. Also report raw n_trades and average holding period (bars).
  - exposure (avg % of equity deployed) — useful context for the fairness caveat below.

Compute for the BENCHMARK (buy-and-hold benchmark_symbol, total-return basis):
  - total_return, CAGR, sharpe_ratio, max_drawdown, final_equity

Sharpe convention (apply identically to both): daily returns, annualized by ×sqrt(252),
risk_free_rate from config (default 0). State the convention in the output.

Return a SIDE-BY-SIDE comparison (strategy vs benchmark) for the shared 5 metrics so the
comparison is apples-to-apples.

FAIRNESS CAVEAT (print this in the report): the strategy is at most
max_concurrent × position_size_pct deployed (default 15 × 8% = 120%, so effectively fully
invested once enough signals exist, but capped by available cash) across many names with
possible cash drag, while the benchmark is 100% in one instrument. Judge the strategy
primarily on risk-adjusted terms (Sharpe, max drawdown) and exposure, not raw return alone.

--------------------------------------------------------------------
PART 4 — PERSISTENCE & API
--------------------------------------------------------------------
- Persist all new params (in the run record), the equity curve, full trade log (with
  per-fill fees), the benchmark equity curve, and both metric sets + the comparison.
- POST /api/backtest accepts all Part-2 params in the body (falling back to config defaults).
- GET /api/backtest/{id} returns: status, strategy metrics, benchmark metrics, the
  side-by-side comparison, equity curves (strategy + benchmark), trade log, the
  slot-vs-capital constraint counts, and (for short runs) the mod-e coverage report.
- Update API_CONTRACT.md. If the frontend needs new fields, note them in SHARED_CHANGES.md;
  don't redesign the frontend here.

--------------------------------------------------------------------
TESTS (mandatory)
--------------------------------------------------------------------
- Fee formula: unit-test the clamp at the min, the per-share band, and the 1% cap.
- Sizing: target below floor → uses floor; insufficient cash → trade skipped; sizing scales
  with current equity (bigger equity ⇒ bigger target $).
- ATR stop: a position whose price crosses entry ∓ 1.5×ATR exits at the next open.
- Selection: given 20 candidates, top_n=10, 15 slots, enough cash → exactly the top 10 by
  score open on that bar; remaining slots fill on later bars; "no capital" skip count correct.
- Per-name cap: an entry that would exceed 30% is clipped/skipped.
- Benchmark: known total-return series → hand-checked total_return and final_equity
  (incl. entry fee).
- Determinism: same data + same params ⇒ identical metrics.
- Keep all mod-e anti-look-ahead and coverage tests green.

ACCEPTANCE
- A long backtest and a short backtest each return: strategy metrics, benchmark metrics, a
  side-by-side comparison, both equity curves, a fee-inclusive trade log, and the
  constraint (slot vs capital) breakdown.
- Changing any Part-2 param via the API changes results as expected (e.g. higher fees lower
  net return; smaller position_size_pct lowers exposure and turnover; max_concurrent 15
  allows more simultaneous holdings than 10).

MANUAL STEPS FOR JAMES
Show me the exact commands to run a long backtest and a short backtest with the default
params, and how to override (e.g.) initial_fund, position_size_pct, and max_concurrent_positions
in the request. Show me where to read the strategy-vs-benchmark comparison in the output.

REPORT BACK
Show the side-by-side strategy-vs-benchmark table for a default long run, the win
rate / avg win / avg loss / profit factor, the turnover and exposure, and the slot-vs-capital
constraint counts. Tell me honestly: is the strategy beating QQQ on a risk-adjusted basis,
and is turnover eating the returns? Then `git commit`.
```

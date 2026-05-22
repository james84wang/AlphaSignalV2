# PHASE 4 — Backtest engine ⚠️ (build before trusting any weights)

> Paste-free workflow: in Claude Code just type — Read prompts/phase-4.md and execute it. Stop and report when done.

Read CLAUDE.md and spec §6.5. Build the BACKTEST ENGINE. This is how we learn whether
the strategy's weights mean anything. Correctness > speed.

GOAL
Walk bar-by-bar through history for a universe, generate signals using ONLY past data,
simulate entries/exits per the risk rules, and report performance metrics.

BUILD
1. backend/app/backtest/engine.py: a walk-forward (NOT vectorised-with-future-leak)
   loop. For each bar T, compute the signal from data up to and including T only, then
   act on bar T+1's open (no peeking). Implement the spec §7 defaults as config:
   stop = 1.5×ATR(14), position size = 2% account risk, max 10 concurrent positions,
   5-bar re-entry cooldown, exit on opposite signal or trailing stop, skip signals within
   3 bars of earnings (use Finnhub earnings calendar if key present; else skip the rule
   and note it). ALL of these read from config.yaml.
2. backend/app/backtest/metrics.py: hit rate, avg win/avg loss, profit factor, max
   drawdown, Sharpe, exposure, # trades, CAGR. Per-trade log retained.
3. Configurable slippage and commission. Default both small but non-zero.
4. Persist backtest runs (params, config hash, metrics, equity curve, trade log) to SQLite.

ANTI-LOOK-AHEAD (critical — write these tests)
- Unit test proving signal(T) is identical whether or not bars > T exist in the data.
- Entries fill on T+1 open, never T close. Stops/exits use intrabar high/low correctly.
- No survivorship-bias shortcut: document this limitation if the S&P 500 list is current
  membership only (it is — flag it).

ACCEPTANCE
- I can run a backtest for the {{UNIVERSE}} universe over {{BACKTEST_YEARS}} years with
  one command and get a metrics summary + equity curve data + trade log.
- Changing a weight in config.yaml changes the backtest result (proves it's wired up).

REPORT BACK
Show the metrics for a baseline run with default weights. Tell me honestly whether the
default strategy looks viable vs the spec's success target (Sharpe > 1.0, max DD < 20%
over 5 yrs, per Open_Questions #13). Do NOT sugar-coat a bad result.

# AlphaSignal modifications — how to run

These five prompts modify the app you already built. Run them **in order** — mod-a changes
the scoring core, and the rest depend on it.

## Where to put them
Drop mod-a.md … mod-e.md into your existing `prompts/` folder
(e.g. `~/projects/alphasignal/prompts/`), next to phase-0.md … phase-7.md.

## The loop (same as before)
1. `cd ~/projects/alphasignal` then `claude`
2. Type:  `Read prompts/mod-a.md and execute it. Stop and report back when done.`
3. Review its report. If happy, `/clear`, then do the next one.

## Recommended order and why
1. **mod-a** — split config + engine into long/short profiles (identical at first). CORE → first.
2. **mod-b** — S&P 1000 universe, editable watchlist, inverse-ETF mapping, two run paths. Depends on a.
3. **mod-e** — per-profile backtest (long on underlying, short on the real inverse ETF) + coverage report. Depends on a/b.
4. **mod-c** — market sentiment data (indices/VIX/Fear&Greed) + daily scheduler. Depends on a/b.
5. **mod-d** — frontend: sentiment bar, 3-section signals, settings UI, inverse-ETF editor, toggles, run buttons. Depends on a/b/c.

> Why mod-e before c/d: it only depends on a+b, and validating/tuning the strategy matters
> more than the sentiment bar or schedule toggle. Don't polish a dashboard for signals you
> don't yet trust. If you'd rather build the UI first, you can run c/d before e — it still works.

## Safety
- Each prompt starts with a `git commit` checkpoint and runs the existing tests first.
- If baseline tests fail at the start of any phase, it STOPS and tells you — fix that first.
- The mod-a golden test (composite = 63.15 → HOLD) must keep passing; that's your proof the
  scoring core still works after the split.

## What the two strategies mean (your intent)
- **Long** = swing-trade in a general uptrend; buy the stock at higher-low pullbacks, exit
  near higher highs.
- **Short** = swing-trade in a general downtrend; you do NOT short-sell — you BUY the stock's
  INVERSE ETF. The signal is computed on the underlying; the dashboard tells you the inverse
  ETF to buy (where one exists).
- The regime filter is what enforces "long only in uptrends, short only in downtrends." The
  two profiles just let you tune each side independently (including separate thresholds).

## Things flagged for your attention
- **S&P 1000** = S&P MidCap 400 + S&P SmallCap 600; no single clean free quote, so the
  dashboard shows the 400 and 600 separately.
- **Inverse ETFs only exist for some names.** Broad index/sector inverses are plentiful;
  single-stock inverse ETFs cover only ~20–30 mega-caps and change over time. There's no API
  for "the inverse ETF of X" — you maintain `data/inverse_etfs.csv` yourself. Short signals on
  unmapped names are flagged "discretionary" (no clean instrument to trade).
- **Inverse-ETF decay.** They reset daily, so over multi-day swing holds they drift from the
  underlying's inverse return. Backtesting the short side by inverting the stock OVERSTATES
  results — so **mod-e backtests the short side on the real inverse ETF's price series** and
  reports a coverage report (what % of your universe is actually testable). Expect the short
  side to be testable on only a small set of names with short histories.
- **Schedule** fires at 8am New York (≈10–11pm AEST). Your Mac must be awake and the backend
  running, or the run is skipped (with catch-up on next startup if enabled). A 24/7 Mac mini
  removes this limitation.

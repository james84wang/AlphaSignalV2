# MOD-A — Split strategy into LONG and SHORT profiles

> Run this FIRST. It changes the scoring core, so everything else (mod-b/c/d) depends on it.
> In Claude Code, type:  `Read prompts/mod-a.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md, trading_strategy_spec.md and config.yaml. Before changing anything, run
`git add -A && git commit -m "checkpoint before mod-a"` and `pytest -q` so we have a clean
baseline. If tests already fail, STOP and tell me before proceeding.

GOAL
Today there is ONE strategy (one set of weights/thresholds/scoring tables). I want TWO
named strategy profiles — "long" and "short" — that are IDENTICAL copies to begin with,
but each independently tunable later (including independent thresholds).

TRADING INTENT (so labels and downstream display make sense)
- LONG profile = swing-trading in a general UPTREND: buy the stock at higher-low pullbacks,
  exit near higher highs. Instrument = the stock itself.
- SHORT profile = swing-trading in a general DOWNTREND: enter at lower-high bounces, exit
  near lower lows. I do NOT short-sell. Instead I BUY THE STOCK'S INVERSE ETF. So the
  SIGNAL is computed on the underlying stock, but the tradeable instrument is its inverse
  ETF (the mapping is handled in mod-b/mod-d, not here).
- Note: the existing regime filter already enforces this — long signals only fire in a
  bull regime (price > EMA200, slope ≥ 0) and short signals only in a bear regime. The two
  profiles are just the long and short sides, tuned independently. Do NOT change the
  scoring or regime logic in this phase — this is a config + plumbing change only.

SIGNAL SEMANTICS (get this right)
- The engine still computes a single composite score per bar from a profile's config.
- The LONG run reports a symbol only when composite ≥ the LONG profile's Buy threshold AND
  regime allows long. Output label: Buy / Strong Buy.
- The SHORT run reports a symbol only when composite ≤ the SHORT profile's Sell threshold
  AND regime allows short. Output label: Sell / Strong Sell (= "buy the inverse ETF").
- A negative composite under the LONG profile means "no long here" — NOT a short signal.
  The two profiles are evaluated independently.
- Each profile owns its OWN: component weights, signal thresholds (keep them independent),
  full scoring tables (candlestick/P3/P5/volume/EMA/S/R/MACD/RSI), and regime settings.

BUILD
1. Refactor config.yaml from a single strategy into:
     strategies:
       long:   { weights, thresholds, scoring_tables, regime }
       short:  { weights, thresholds, scoring_tables, regime }
   Migrate the CURRENT config into BOTH profiles verbatim, so behaviour is unchanged on
   day one. Keep a non-strategy section for shared stuff (data, universe, risk).
2. Update backend/app/config.py: load and validate BOTH profiles (each must pass the
   weights-sum-to-100 check independently). Provide a get_strategy(name) accessor.
3. Update the scoring/composite engine so the daily runner and any caller pass a strategy
   name ("long" | "short") and the engine uses that profile's numbers throughout.
4. Update SQLite: the signals/runs tables must record WHICH strategy produced each row
   (add a `strategy` column). Existing data can be left as-is or backfilled as "long".
5. Update the API where config is exposed/edited so it is per-strategy
   (e.g. GET/PUT /api/config/{strategy}). Update API_CONTRACT.md accordingly.

TESTS
- The Example_Calc golden test (composite = 63.15 → HOLD) must STILL pass against the
  default LONG profile (and SHORT, since identical). Do not break it.
- Add a test proving long and short profiles can diverge: change one weight in the short
  profile only, confirm the long profile's output is unaffected.

ACCEPTANCE
- config.yaml has two identical profiles; both validate.
- A daily run can be invoked for "long" or "short" and stores the strategy on each row.
- All existing tests still pass.

REPORT BACK
Show me the new config.yaml structure (just the shape, not every number), confirm the
golden test passes for both profiles, and list anything in the old code that assumed a
single strategy that you had to change. Then `git commit`. Do NOT start mod-b.
```

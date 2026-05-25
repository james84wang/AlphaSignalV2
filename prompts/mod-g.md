# MOD-G — "About" section (live documentation: Scope, Strategy, Backtest)

> Depends on mod-d (the frontend nav with Dashboard / Settings / Backtest). Run AFTER mod-d.
> In Claude Code:  `Read prompts/mod-g.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md, API_CONTRACT.md, config.yaml, trading_strategy_spec.md, and the actual
backtest code (backend/app/backtest/ incl. mod-e/mod-f changes). Run
`git commit -m "checkpoint before mod-g"` first.

GOAL
Add a fourth top-level section to the app — "About" — alongside Dashboard, Settings, and
Backtest. It is a human-readable reference so I (and anyone I show it to) can always
understand what this app does, how the strategy works, and the limitations of the backtest
— instead of treating the app as a black box. It must stay current as the app evolves.

ARCHITECTURE — single source of truth (important)
- Create docs/ABOUT.md as the SINGLE source of truth for all About content, organised into
  the four tabs below (use clear markdown headings per tab).
- The frontend About section RENDERS docs/ABOUT.md (fetch it via a small backend endpoint,
  e.g. GET /api/about, or bundle/serve the markdown — your call, but there must be ONE file,
  not content duplicated in React). Render markdown to nicely formatted HTML (tables, dot
  points, headings) consistent with the app's dark, TradingView-inspired theme.
- Do NOT hand-duplicate strategy numbers into prose that will drift. Where the doc states
  weights/thresholds/defaults, GENERATE them from the real config.yaml at build time (or
  render a live snapshot), and say "as configured" so the reader knows it reflects current
  settings.

CONTENT — GENERATE FROM THE REAL APP (not assumptions)
Read the actual config, spec, and code and write accurate content. Seed each tab with the
points below but expand them truthfully based on what is actually built.

TAB 1 — "Overview & Scope"  (pick this or a better name)
- One-paragraph purpose: personal-use US-equity analysis & strategy builder (NOT commercial,
  NOT financial advice, NOT for day trading).
- Trading universe: list what's actually scanned (S&P 500, S&P 1000 = MidCap 400 +
  SmallCap 600, plus user watchlist; deduplicated).
- Data sources mapped to each use (build a table):
    * Daily OHLCV / backtest history  -> (yfinance, as built)
    * Quotes / earnings (if used)      -> (Finnhub, as built)
    * Market overview indices/VIX      -> (tickers used, as built in mod-c)
    * CNN Fear & Greed                 -> (source actually used, as built in mod-c)
  State the data delay (up to ~1 hour; daily bars) for each where relevant.
- APIs used and any 3rd-party tools/libraries (FastAPI, pandas/pandas-ta, lightweight-charts
  with its TradingView attribution, TanStack Query, APScheduler, etc. — read deps and list
  what's real).
- High-level architecture & tech stack: a short diagram-in-words (Python/FastAPI backend +
  React/Vite/TS frontend + SQLite/Parquet storage), and how a daily run flows.
- GitHub link: insert a placeholder {{GITHUB_URL}} and ASK ME to confirm the URL (the repo
  may not be pushed yet — if I don't have one, leave the placeholder and note "not yet
  published").
- Footer line: "Created by James Wang, May 2026" with a small photo of me (see MANUAL STEP),
  and an auto-updated "Last updated: <date>" stamp.

TAB 2 — "Strategy Details"  (pick this or a better name)
- Explain the LONG strategy (swing-long in an uptrend: buy the stock at higher-low
  pullbacks, exit near higher highs) and the SHORT strategy (swing in a downtrend, executed
  by BUYING THE INVERSE ETF — not short-selling).
- Explain the scoring system: the 8 components, that each outputs a sub-score in [-100,+100],
  how weights (summing to 100) combine into a composite score, and the signal thresholds
  (Strong Buy/Buy/Hold/Sell/Strong Sell). Render the CURRENT weights & thresholds per profile
  from config.
- Explain how the app identifies a BULLISH vs BEARISH market: the EMA200 regime filter
  (price vs EMA200 + slope) and how it gates long vs short so the app "never trades against
  momentum."
- When to apply each strategy: long in confirmed uptrends, short (inverse ETF) in confirmed
  downtrends; both can be range-bound-gated.
- Limitations of the strategy (dot points): it's a daily-timeframe reversal/momentum model,
  not predictive; signals can whipsaw in choppy/range markets; inverse-ETF execution adds
  daily-reset decay on multi-day holds; thresholds/weights are user-tuned and can overfit;
  no fundamental or news awareness beyond an optional earnings blackout.

TAB 3 — "Backtest Details & Limitations"  (pick this or a better name)
- Explain the backtest logic in plain English so it's not a black box:
    * signal computed on today's CLOSE, order filled at the NEXT day's OPEN;
    * portfolio simulation: initial fund, fixed-fractional position sizing on current
      equity (with floor), max concurrent positions, per-name cap, Top-N ranked selection
      by score, 1.5×ATR stop, exit on opposite signal;
    * fees modelled (per-share with min and % cap, charged both sides);
    * benchmark = buy-and-hold (default QQQ) on a total-return basis;
    * returns computed on adjusted/total-return prices (dividends included) for both sides.
  Render the CURRENT backtest defaults from config.
- Limitations of the backtest, as CLEAR DOT POINTS, including at minimum:
    * Data delay & granularity: daily bars only; free data may be delayed/imperfect.
    * Lookback limit: how far back the data realistically goes (state it), and that single-
      stock inverse ETFs have very short histories → the SHORT side is testable on few names
      for short windows (reference the mod-e coverage report).
    * SURVIVORSHIP BIAS (explain it explicitly with this example): backtesting "the S&P 500
      over 5 years" using TODAY'S 500 members only tests companies that survived and were
      promoted into the index, making returns look better than reality ("fake-good"). The
      app uses CURRENT-membership lists, not point-in-time membership, so results are
      optimistic. Note that point-in-time membership data would be needed to fix this.
    * Inverse-ETF decay makes synthetic short results overstated; real-ETF testing limits
      coverage (cross-reference Tab 2 and mod-e).
    * No modelling of: liquidity/market impact for thin names, borrow availability, taxes;
      slippage is a simple assumption; corporate actions handled only via adjusted prices.
    * Past performance does not predict future results; this is research, not advice.

TAB 4 — "Changelog / Version"  (the "live document" mechanism)
- A reverse-chronological changelog (most recent first). Seed it with the phases/mods built
  so far (initial build + mod-a…mod-g) at a high level.
- Show the app version and an auto-updated "Last updated" date.

KEEP IT LIVE (do this so the doc can't silently rot)
- Append a STANDING RULE to CLAUDE.md under "Definition of Done": "Every change that affects
  scope, data sources, strategy logic, or backtest behaviour MUST update docs/ABOUT.md
  (relevant tab) and add a dated entry to the Changelog tab in the same commit." This makes
  future mod prompts responsible for keeping About current.
- Auto-stamp "Last updated" from the file's git last-commit date (or build date) so I don't
  maintain it by hand.

MANUAL STEPS FOR JAMES
1. PHOTO: tell me exactly where to put my photo (e.g. frontend/src/assets/james.jpg),
   what filename and rough dimensions/format to use, and pause for me to add it. If it's
   missing, render a neutral placeholder so the app still builds.
2. GITHUB: ask me for the repo URL to drop into {{GITHUB_URL}} (or confirm there isn't one
   yet).

ACCEPTANCE
- A new "About" section appears in the app nav with four tabs, rendering docs/ABOUT.md.
- Content reflects the REAL config/spec/code (weights, thresholds, defaults, data sources),
  not placeholders, except the GitHub URL and photo which I provide.
- The survivorship-bias point is present and clearly explained with the S&P 500 example.
- CLAUDE.md now contains the standing rule to keep ABOUT.md updated.
- "Last updated" stamps automatically.

REPORT BACK
Show me the four rendered tabs (screenshots or a short walk-through), confirm the numbers
were pulled from the real config, and show me the standing rule you added to CLAUDE.md.
Then `git commit`.
```

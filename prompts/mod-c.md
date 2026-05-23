# MOD-C — Market sentiment data + daily scheduler

> Run AFTER mod-b. In Claude Code:  `Read prompts/mod-c.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md and API_CONTRACT.md. Run `git commit -m "checkpoint before mod-c"` and
`pytest -q` first. STOP if baseline tests fail.

GOAL
Two backend additions: (1) a market sentiment data feed for the dashboard header, and
(2) a daily scheduler that can run both strategies automatically, toggleable on/off.

PART 1 — MARKET SENTIMENT DATA
Add a service + endpoint GET /api/market/overview returning the latest level and daily
% change for each of these, plus the CNN Fear & Greed value:
  - S&P 500            (suggested ticker ^GSPC)
  - NASDAQ Composite   (suggested ^IXIC)
  - NASDAQ 100         (suggested ^NDX)
  - VIX                (suggested ^VIX)
  - XLK (tech sector ETF)  (ticker XLK)
  - S&P MidCap 400     (suggested ^SP400)   ┐ shown in place of a single "S&P 1000"
  - S&P SmallCap 600   (suggested ^SP600)   ┘ quote, which has no clean free feed
  - CNN Fear & Greed Index (0–100 + label, e.g. "Extreme Fear")

Rules:
- VERIFY each ticker actually resolves on the provider at build time. If one doesn't,
  find the correct symbol or mark that tile "unavailable" — never invent a value.
- For a single "S&P 1000" number: if you can find a reliable free quote, use it; otherwise
  show MidCap 400 and SmallCap 600 separately (preferred) or a clearly-labelled blend.
  Tell me which you did and why.
- Fear & Greed: CNN publishes an undocumented JSON data endpoint
  (https://production.dataviz.cnn.io/index/fearandgreed/graphdata) that usually needs a
  browser-like User-Agent header. Try that first; fall back to scraping the public page;
  if both fail, return "unavailable". This is public market data; wrap it behind the data
  abstraction, cache it (it only updates a few times a day), and FAIL GRACEFULLY — a
  broken scrape must never crash the dashboard.
- Cache overview data briefly (e.g. 10–15 min) to respect rate limits; 1-hour delay is
  fine (this is not day-trading).

PART 2 — DAILY SCHEDULER
- Add APScheduler (or equivalent) inside the backend. One daily job that runs BOTH the
  long and short strategies over the combined universe.
- Schedule time: 08:00 in the America/New_York timezone (before the 09:30 ET open). Use
  the IANA tz name so US daylight-saving shifts are handled automatically — do NOT hard-
  code a fixed UTC/AEST offset.
- Persist an on/off setting (SQLite or a settings file). Expose:
    GET  /api/schedule        -> { enabled, time, tz, last_run, next_run }
    PUT  /api/schedule        -> { enabled: true|false }
- "Catch-up": if enabled and the scheduled run was missed (machine asleep), run once on
  next backend startup if today's run hasn't happened yet. Make this behaviour explicit
  and configurable.
- Record scheduled runs in the runs table like manual runs.
- Update API_CONTRACT.md.

HONEST CAVEAT TO SURFACE
This is a LOCAL app: the scheduled run only fires if my MacBook is awake and the backend
is running at that time (≈10–11pm AEST). State this plainly in the README and in the
schedule API response (e.g. a note field), so I'm not surprised when a closed-lid run is
skipped. Don't over-engineer a fix; just make the catch-up behaviour clear.

ACCEPTANCE
- /api/market/overview returns sensible numbers for the tiles (or labelled "unavailable").
- Toggling /api/schedule on/off persists across backend restarts.
- I can see last_run / next_run, and a missed run catches up on startup when enabled.

MANUAL STEPS FOR JAMES
Show me curl commands to: fetch the market overview, turn the schedule on, turn it off,
and check next_run. Explain in plain English what time the run fires in my AEST timezone
right now (account for current US daylight-saving status).

REPORT BACK
Show a sample /api/market/overview payload and the Fear & Greed source you ended up using.
Then `git commit`. Do NOT start mod-d.
```

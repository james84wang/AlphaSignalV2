# MOD-B — S&P 1000 universe, editable watchlist, inverse-ETF mapping, dual run

> Run AFTER mod-a. In Claude Code:  `Read prompts/mod-b.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md and API_CONTRACT.md. Run `git commit -m "checkpoint before mod-b"` and
`pytest -q` first. STOP if baseline tests fail.

GOAL
Expand the scan universe to include the S&P 1000, let me edit my watchlist via the API,
add an inverse-ETF mapping for the short strategy, and give me two run paths (long/short)
over the combined universe.

BACKGROUND YOU MUST HANDLE
- "S&P 1000" is NOT a single downloadable index. It = S&P MidCap 400 + S&P SmallCap 600.
  Build the S&P 1000 constituent list by combining the 400 and 600 member lists (e.g.
  scrape the two Wikipedia constituent tables, or another reliable source) and CACHE it.
  Current-membership only (survivorship caveat), same as the existing S&P 500 list.
- Some tickers won't resolve on the free feed. Never let one bad symbol abort a run.

BUILD
1. Universe (backend/app/data/universe.py):
   - Add an "sp1000" universe built from the 400+600 constituents, cached like sp500.
   - Add a combined universe = sp500 ∪ sp1000 ∪ watchlist, DEDUPLICATED by symbol. Make
     this the default scan universe in config.yaml.
2. Watchlist CRUD (persist in SQLite: symbol, added_at, optional note):
   - GET /api/watchlist, POST /api/watchlist {symbol}, DELETE /api/watchlist/{symbol}.
   - Validate the symbol format; optionally verify it resolves on the data provider before
     saving, returning a clear error if not. Keep data/watchlist.csv as a one-time seed.
3. INVERSE-ETF MAPPING (for the short strategy's tradeable instrument):
   - Create a user-editable file data/inverse_etfs.csv with columns:
       underlying_symbol, inverse_etf_symbol, leverage, note
   - Seed it with rock-solid broad-index inverses and VERIFY each resolves on the provider:
       SPY -> SH (-1x), QQQ -> PSQ (-1x), DIA -> DOG (-1x)
     Add a few sector/index ones you can verify; DO NOT invent single-stock inverse
     tickers — I will add the single-stock names I care about myself (most stocks have NO
     inverse ETF, and the single-stock lineup changes often).
   - Loader: backend reads this file into a {underlying -> inverse_etf} map.
   - Expose GET /api/inverse-etfs (return the current map). (Editing from the UI is optional
     and handled in mod-d.)
   - When the SHORT run produces a signal for an underlying, ATTACH the mapped inverse ETF
     symbol to that signal row (new field, e.g. inverse_etf). If there is no mapping,
     set it to null and mark the signal "no inverse ETF — discretionary". Do NOT block the
     signal; just flag that there's no clean instrument.
4. Dual run:
   - Two endpoints/commands: run the LONG strategy and run the SHORT strategy, each over
     the combined universe, reusing the mod-a strategy-aware engine.
     e.g. POST /api/runs/daily {strategy: "long"|"short"} and a scripts flag.
   - Each run stores its strategy on every signal row; short-run rows also store inverse_etf.
   - Watchlist overlap with S&P500/1000 is fine — dedupe by symbol so each symbol is scored
     once per strategy per run.
5. Update API_CONTRACT.md for the new watchlist, inverse-etf, and run endpoints.

ACCEPTANCE
- I can add/remove a watchlist symbol via the API and see it persist.
- GET /api/inverse-etfs returns the seeded map; a short signal on SPY (or another mapped
  underlying) carries the correct inverse_etf; an unmapped underlying carries null + flag.
- A long run and a short run each complete over the combined universe, tagged correctly.

MANUAL STEPS FOR JAMES
1. Show me the exact curl commands to add/remove/list a watchlist symbol and to trigger a
   long run and a short run. 2. Show me the format of data/inverse_etfs.csv and one example
   row so I can add my own single-stock inverse ETFs (e.g. for the mega-caps I trade).

REPORT BACK
Tell me how many symbols the combined universe resolved to, how long a full long run took,
which inverse-ETF seeds you verified, and any symbols that failed to fetch. Then
`git commit`. Do NOT start mod-c.
```

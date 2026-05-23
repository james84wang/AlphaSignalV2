# MOD-D — Frontend: sentiment bar, 3-section signals, settings UI, toggles, dual run

> Run LAST, after mod-a/b/c. In Claude Code:  `Read prompts/mod-d.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md and API_CONTRACT.md (now updated by mod-a/b/c). Run
`git commit -m "checkpoint before mod-d"` first. Consume the backend only via the
contract. Keep the TradingView attribution link in the footer.

GOAL
Wire all the new backend capabilities into the UI: a market sentiment header, a 3-section
signal dashboard, a fuller Strategy settings area with two profiles, watchlist editing,
an inverse-ETF mapping editor, two run buttons, and a daily-schedule toggle.

BUILD
1. DASHBOARD — MARKET OVERVIEW HEADER (top of dashboard)
   - A row of tiles from GET /api/market/overview: S&P 500, S&P MidCap 400, S&P SmallCap
     600 (these two stand in for S&P 1000), XLK, NASDAQ Composite, NASDAQ 100, VIX, and CNN
     Fear & Greed (value + label, colour-coded). Each tile: level + daily % change,
     green/red. Tiles that returned "unavailable" show a muted placeholder, not an error.

2. DASHBOARD — SIGNALS IN 3 SECTIONS (below the header)
   - Section 1: LONG SIGNALS (swing-long) — long-strategy results (Buy / Strong Buy),
     ranked strongest first.
   - Section 2: SHORT SIGNALS (swing via inverse ETF) — short-strategy results
     (Sell / Strong Sell), ranked strongest first. Include an "Inverse ETF to buy" column
     from the signal's inverse_etf field. Rows with no mapping show "no inverse ETF —
     discretionary" in a muted style so I know they aren't cleanly tradeable.
   - Section 3: WATCHLIST SIGNALS — only my watchlist symbols, showing whatever fired for
     them, each row clearly tagged Buy or Sell. For Sell rows, also show the inverse ETF
     (or the discretionary flag).
   - Each row click → existing Symbol view with the audit panel. Show which strategy/run
     and the run timestamp.

3. TWO RUN BUTTONS
   - "Run Long Signals" and "Run Short Signals", each calling the dual-run endpoints over
     the combined universe. Show progress + completion; refresh the relevant dashboard
     section when done. Disable a button while its run is in progress.

4. STRATEGY SETTINGS (two profiles)
   - A tab/toggle to switch between editing the LONG profile and the SHORT profile.
   - For the selected profile, make editable and savable (PUT /api/config/{strategy}):
       * component weights (with the live "must sum to 100" validator),
       * signal thresholds (independent per profile — long and short can differ),
       * the full scoring tables (candlestick / P3 / P5 / volume / EMA / S/R / MACD / RSI),
         each rendered as an editable table of sub-scores.
   - Warn that changing a profile invalidates that profile's prior signals. Make it obvious
     which profile is being edited so I never confuse long vs short.

5. WATCHLIST EDITING
   - A panel to add a symbol (POST /api/watchlist), remove one (DELETE), and list current
     watchlist (GET). Clear error if a symbol is invalid.

6. INVERSE-ETF MAPPING EDITOR (settings)
   - Show the current map from GET /api/inverse-etfs (underlying -> inverse ETF). Let me add
     or edit rows so I can map the single-stock inverse ETFs I actually trade. If mod-b only
     built a GET endpoint, add the small PUT/POST needed and note it in SHARED_CHANGES.md —
     do not redesign the backend yourself.

7. SCHEDULE TOGGLE
   - A switch bound to GET/PUT /api/schedule that turns the daily auto-run on/off.
   - Display next_run and last_run, and show the backend's plain-English note about the
     machine needing to be awake. When ON, make clear it runs BOTH strategies at 8am New
     York time.

GENERAL
- Use TanStack Query; every fetch has loading + error states (the data layer and the CNN
  scrape can fail — never render a blank screen).
- Keep the dark, TradingView-inspired layout consistent with the existing app.

ACCEPTANCE
- From the UI I can: read the market overview; run long and short; see the 3 signal
  sections correctly populated (short + watchlist sells show the inverse ETF or the
  discretionary flag); edit either profile's weights/thresholds/scoring tables and save;
  add/remove watchlist symbols; edit the inverse-ETF map; and toggle the daily schedule.
- Numbers shown match what the API returns.

REPORT BACK
Walk me through each screen (short description or screenshots) and the run command. Note
anything you needed that wasn't in the contract (add it to SHARED_CHANGES.md rather than
changing the backend yourself). Then `git commit`.
```

# PHASE 6 — Frontend (dashboard, charts, settings, backtest UI)

> Paste-free workflow: in Claude Code just type — Read prompts/phase-6.md and execute it. Stop and report when done.

Read CLAUDE.md and API_CONTRACT.md. Build the AlphaSignal FRONTEND. Consume the backend
API only via the contract. Use lightweight-charts (TradingView) for charts and keep the
required TradingView attribution link visible in the footer.

GOAL
A clean, TradingView-inspired UI with four areas: Dashboard, Symbol view, Strategy
settings, Backtest.

BUILD
1. App shell: dark theme, sidebar with watchlist + universe selector, header with the
   {{APP_NAME}} logo from {{LOGO_PATH}}.
2. Dashboard: today's ranked signal table (Strong Buy → Strong Sell) with colour-coded
   composite scores; click a row → Symbol view.
3. Symbol view: lightweight-charts candlestick chart with EMA overlays (20/50/100/200),
   plus indicator panes for MACD and RSI. Show the per-bar audit panel: every component's
   sub-score, weight, weighted contribution, and the regime gate status — so I can SEE
   why the composite is what it is.
4. Strategy settings: editable weights (sliders/inputs) with a live "must sum to 100"
   validator, editable signal thresholds, and the per-pattern scoring tables. Save →
   PUT /api/config. Show a warning that changing weights invalidates prior signals.
5. Backtest: form to pick universe, date range, and (optionally) override weights; run
   button; results view with equity curve, the metrics table, and the trade log.
6. Use TanStack Query for fetching; show loading + error states everywhere (the data
   layer can fail — never show a blank screen).

ACCEPTANCE
- I can: see today's signals, open a symbol, read why it scored that way, change a weight,
  re-run signals, and run a backtest — all from the UI.
- Charts render real cached data and match the numbers from the API.

REPORT BACK
Walk me through each screen with screenshots or a short description, and the run command.

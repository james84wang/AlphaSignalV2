# PHASE 5 — Backend API (expose signals, config, backtest)

> Paste-free workflow: in Claude Code just type — Read prompts/phase-5.md and execute it. Stop and report when done.

Read CLAUDE.md. Build the FastAPI layer that the frontend will consume. FIRST write
API_CONTRACT.md documenting every endpoint + JSON shape, then implement it.

GOAL
HTTP endpoints for: latest & historical signals, single-symbol detail + OHLCV for
charting, current config (weights/thresholds), updating config, triggering a daily run,
and running/fetching backtests.

BUILD (suggested endpoints — adjust in API_CONTRACT.md)
- GET  /api/signals?date=&universe=           → ranked signal table
- GET  /api/symbols/{symbol}/bars?range=       → OHLCV for charting (lightweight-charts shape)
- GET  /api/symbols/{symbol}/signal?date=      → full audit object (all sub-scores)
- GET  /api/config                              → current weights/thresholds/scoring tables
- PUT  /api/config                              → update weights (validate sum=100), version it
- POST /api/runs/daily                          → trigger a daily signal run
- POST /api/backtest                            → start a backtest (params in body)
- GET  /api/backtest/{id}                        → status + metrics + equity curve + trades
- Long jobs (daily run, backtest) run in the background; expose a status endpoint.

ACCEPTANCE
- API_CONTRACT.md exists and matches the implementation.
- Auto-generated FastAPI /docs works; I can hit every endpoint from the docs page.
- Updating weights via PUT /api/config and re-running signals reflects the change.

REPORT BACK
Show me API_CONTRACT.md and a curl example for each endpoint. Do NOT start Phase 6.

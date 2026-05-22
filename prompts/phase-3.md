# PHASE 3 — Daily signal runner (CLI + persistence)

> Paste-free workflow: in Claude Code just type — Read prompts/phase-3.md and execute it. Stop and report when done.

Read CLAUDE.md. Build the DAILY SIGNAL RUNNER that ties data + scoring together.

GOAL
A command that, given a universe/watchlist and a date (default: latest trading day),
computes signals for every symbol and stores the results.

BUILD
1. backend/app/db/: SQLAlchemy models + SQLite for a `signals` table (date, symbol,
   composite, signal, regime flags, per-component sub-scores as JSON) and a `runs` table
   (run timestamp, universe, config hash, # symbols, duration).
2. scripts/run_daily.py: load universe → ensure data is cached/fresh → compute signals
   for each symbol for the target date → persist to SQLite. Print a ranked table
   (strongest Buy → strongest Sell). Store the config hash so I know which weights produced it.
3. Handle missing data per-symbol without aborting the whole run.

ACCEPTANCE (maps to spec §8 #1–#4)
- One command produces a stored, ranked daily signal table for the {{UNIVERSE}} universe.
- Per-component sub-scores and regime status are queryable from SQLite.
- A 100-symbol × 1-year run completes in under 5 minutes on an M-series Mac
  (spec acceptance #6). If it can't, tell me why and propose a fix (e.g. parallel fetch).

MANUAL STEPS FOR JAMES
Show me the exact command to run today's signals, and a sample SQL query (or a tiny
helper script) to inspect stored results.

REPORT BACK
Show the top 10 and bottom 10 ranked signals from a real run on the watchlist.
Do NOT start Phase 4.

# PHASE 7 — (Optional) Desktop packaging + scheduled daily run

> Paste-free workflow: in Claude Code just type — Read prompts/phase-7.md and execute it. Stop and report when done.

Read CLAUDE.md. OPTIONAL polish. Only do this once Phases 0–6 are stable.

GOAL
Make {{APP_NAME}} feel like a desktop app and run the daily scan automatically.

BUILD (recommend the SIMPLEST path for a beginner)
1. A one-click launcher: a script (or a small pywebview wrapper) that starts the backend,
   serves the built frontend, and opens it in a native window. Document the trade-offs of
   pywebview vs Tauri vs Electron given our Python backend (Python bundling is the hard
   part — be honest about it). Default to the lowest-complexity option that works on both
   macOS and Windows.
2. Scheduled daily run: instructions to schedule scripts/run_daily.py via cron (mac) and
   Task Scheduler (windows) to run after US market close (account for my AEST timezone).

ACCEPTANCE
- I can launch the app from a single icon/script and it opens in its own window.
- The daily scan runs automatically and I can see fresh signals the next morning (AEST).

MANUAL STEPS FOR JAMES
Give me exact, numbered steps for the scheduler on both macOS and Windows, including how
to verify it ran.

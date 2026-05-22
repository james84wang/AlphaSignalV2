# PHASE 0 — Scaffolding & dev environment

> Paste-free workflow: in Claude Code just type — Read prompts/phase-0.md and execute it. Stop and report when done.

You are setting up a brand-new project called {{APP_NAME}} (AlphaSignal). Read CLAUDE.md
first — but it doesn't exist yet, so your FIRST task is to create the repo and CLAUDE.md.

GOAL
Create the full repo skeleton, dependency setup, config loader, and a "hello world" that
proves the backend and frontend both run on my machine.

BUILD
1. Initialise a git repo and create the exact folder layout from the brief I will paste
   below. (I will paste the CLAUDE.md content — save it verbatim as CLAUDE.md.)
2. Create config.yaml by translating EVERY weight, threshold and scoring table from
   trading_strategy_spec.md and trading_strategy_template.xlsx into structured YAML.
   Include: component weights (§2.2), signal thresholds (§2.1), regime filter rules (§3),
   and the full sub-score tables for candlestick, P3, P5, volume, EMA, S/R, MACD, RSI (§4).
   Add the §7 "open questions" defaults as a `risk:` and `universe:` section.
3. backend/app/config.py: load config.yaml into typed pydantic models and VALIDATE that
   component weights sum to 100 (fail loudly if not).
4. Minimal FastAPI app (backend/app/main.py) with a GET /health endpoint returning
   {status, app, version, weights_valid}.
5. Minimal React+Vite+TS+Tailwind frontend that calls /health and renders the result.
   Put a placeholder logo at {{LOGO_PATH}} (I'll replace it).
6. pyproject.toml with all backend deps + ruff + pytest. frontend/package.json with deps.
7. scripts/dev.sh (mac/linux) and scripts/dev.ps1 (windows): start backend + frontend.
8. README.md: exact, beginner-level setup steps (install Python, Node, how to run).
9. .gitignore (ignore data/, .venv/, node_modules/, *.parquet, .env).

ACCEPTANCE
- `pytest -q` runs (even if only 1 trivial test) and passes.
- I can run one command and see the health check succeed in the browser.
- config.py rejects a tampered config where weights ≠ 100.

MANUAL STEPS FOR JAMES
List, as numbered copy-paste commands, exactly how to: install Python 3.11+, install
Node LTS, create the virtualenv, install deps, and run scripts/dev.sh — for BOTH macOS
and Windows. Assume I have nothing installed yet.

REPORT BACK
Confirm the layout, show me the config.yaml structure, and tell me the run command.
Do NOT start Phase 1.

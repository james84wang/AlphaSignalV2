# Shared Changes Requests

This file tracks requested changes to shared files (config.yaml, pyproject.toml, CLAUDE.md)
that individual phase sessions cannot edit directly.

---

## Phase 3 → universe.py path bug

**File:** `backend/app/data/universe.py`

**Issue:** `_REPO_ROOT = Path(__file__).resolve().parents[4]` resolves one level too high
(`Claude/Code/` instead of `AlphaSignalV2/`), so the default watchlist path is
`Claude/Code/data/watchlist.csv` rather than `AlphaSignalV2/data/watchlist.csv`.

**Fix:** Change `parents[4]` → `parents[3]` on lines 19–20 of `universe.py`.

**Workaround in place:** `scripts/run_daily.py` passes `watchlist_path=_WATCHLIST_PATH`
explicitly so Phase 3 is unaffected. But the bug will surface if anyone calls
`Universe()` without an explicit path.

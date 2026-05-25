"""AlphaSignal FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import load_config
from backend.app.db.backtest_models import init_backtest_db
from backend.app.db.models import WatchlistEntry, get_engine, init_db, migrate_db, make_session_factory
from sqlalchemy import select

from backend.app.api.signals import router as signals_router
from backend.app.api.symbols import router as symbols_router
from backend.app.api.config_routes import router as config_router
from backend.app.api.runs import router as runs_router
from backend.app.api.backtest import router as backtest_router
from backend.app.api.watchlist import router as watchlist_router
from backend.app.api.inverse_etfs_routes import router as inverse_etfs_router
from backend.app.api.market import router as market_router
from backend.app.api.schedule import router as schedule_router
from backend.app.scheduler import init_scheduler, shutdown_scheduler

logger = logging.getLogger(__name__)

# frontend/dist/ is at repo_root/frontend/dist; main.py is at repo_root/backend/app/main.py
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO_ROOT.parent / "data"
_DB_PATH = _DATA_DIR / "signals.db"
_WATCHLIST_CSV = _REPO_ROOT / "data" / "watchlist.csv"

@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    init_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="AlphaSignal",
    version="0.1.0",
    description="Personal US equity scoring engine — strategy signals, config, and backtests.",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _seed_watchlist_from_csv() -> None:
    """If the watchlist table is empty, seed it from data/watchlist.csv."""
    if not _WATCHLIST_CSV.exists():
        return
    try:
        import pandas as pd
        df = pd.read_csv(_WATCHLIST_CSV)
        if "symbol" not in df.columns:
            return
        symbols = df["symbol"].str.strip().str.upper().dropna().tolist()
        if not symbols:
            return

        factory = make_session_factory(_DB_PATH)
        with factory() as session:
            existing_count = session.execute(select(WatchlistEntry)).scalars().first()
            if existing_count is not None:
                return  # already seeded

            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for sym in symbols:
                session.add(WatchlistEntry(symbol=sym, added_at=now, note="seeded from watchlist.csv"))
            session.commit()
            logger.info("Seeded watchlist DB with %d symbols from watchlist.csv", len(symbols))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not seed watchlist from CSV: %s", exc)


# Ensure SQLite tables exist and run schema migrations at startup.
_engine = init_db(_DB_PATH)
migrate_db(_engine)
init_backtest_db()
_seed_watchlist_from_csv()

app.include_router(signals_router)
app.include_router(symbols_router)
app.include_router(config_router)
app.include_router(runs_router)
app.include_router(backtest_router)
app.include_router(watchlist_router)
app.include_router(inverse_etfs_router)
app.include_router(market_router)
app.include_router(schedule_router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    cfg = load_config()
    return {
        "status": "ok",
        "app": "AlphaSignal",
        "version": "0.1.0",
        "weights_valid": cfg.weights_valid,
    }


# ── SPA static-file serving (production build) ────────────────────────────────
if _DIST.is_dir():
    _assets = _DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """Serve static files or fall back to index.html for SPA routing."""
        # Never serve HTML for /api/* — return a clear JSON 404 instead.
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail=f"API route not found: /{full_path}")
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        index = _DIST / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built")
        # no-cache so browsers always fetch fresh HTML and pick up new JS bundle hashes
        return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

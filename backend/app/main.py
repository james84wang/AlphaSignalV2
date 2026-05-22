"""AlphaSignal FastAPI entry point."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import load_config
from backend.app.db.backtest_models import init_backtest_db
from backend.app.db.models import init_db

from backend.app.api.signals import router as signals_router
from backend.app.api.symbols import router as symbols_router
from backend.app.api.config_routes import router as config_router
from backend.app.api.runs import router as runs_router
from backend.app.api.backtest import router as backtest_router

# frontend/dist/ is at repo_root/frontend/dist; main.py is at repo_root/backend/app/main.py
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(
    title="AlphaSignal",
    version="0.1.0",
    description="Personal US equity scoring engine — strategy signals, config, and backtests.",
)

app.add_middleware(
    CORSMiddleware,
    # Allow Vite dev server in development; in production the frontend is
    # served from the same origin so CORS isn't needed, but keeping the
    # dev origins here is harmless.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure SQLite tables exist at startup.
init_db()
init_backtest_db()

app.include_router(signals_router)
app.include_router(symbols_router)
app.include_router(config_router)
app.include_router(runs_router)
app.include_router(backtest_router)


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
# Mounted AFTER all API routes so API paths always win.
# Only active when `frontend/dist/` exists (i.e. after `npm run build`).
if _DIST.is_dir():
    # Serve hashed JS/CSS/image bundles from dist/assets/
    _assets = _DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """Serve static files or fall back to index.html for SPA routing."""
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        index = _DIST / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built")
        return FileResponse(index)

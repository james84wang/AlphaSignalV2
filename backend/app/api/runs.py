"""POST /api/runs/daily and GET /api/runs/daily/{job_id} — trigger & poll daily runs."""
from __future__ import annotations

import json
import logging
import threading
import time as _time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.app.api.jobs import create_job, fail_job, finish_job, get_job, update_job_progress
from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.inverse_etfs import load_inverse_etf_map
from backend.app.data.universe import (
    Universe,
    fetch_nasdaq100_symbols,
    fetch_sp400_symbols,
    fetch_sp500_symbols,
    fetch_sp600_symbols,
    fetch_sp1000_symbols,
)
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.db.models import Run, Signal, WatchlistEntry, config_hash, make_session_factory
from backend.app.scoring.composite import run_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_DATA_DIR = _REPO_ROOT.parent / "data"
_DB_PATH = _DATA_DIR / "signals.db"
_WATCHLIST_PATH = _REPO_ROOT / "data" / "watchlist.csv"
_HISTORY_DAYS = 400

_VALID_UNIVERSES = ("watchlist", "sp500", "combined", "midcap", "smallcap", "nasdaq100")


class DailyRunRequest(BaseModel):
    universe: str = "combined"
    strategy: str = "long"
    date: str | None = None


@router.post("/daily", status_code=202)
def trigger_daily_run(body: DailyRunRequest) -> dict:
    """Trigger a background daily signal run."""
    if body.universe not in _VALID_UNIVERSES:
        raise HTTPException(422, detail=f"universe must be one of {_VALID_UNIVERSES}")
    if body.strategy not in ("long", "short"):
        raise HTTPException(422, detail="strategy must be 'long' or 'short'")

    target_str = body.date or str(date.today())
    try:
        target_date = date.fromisoformat(target_str)
    except ValueError:
        raise HTTPException(422, detail="date must be YYYY-MM-DD")

    job = create_job("daily_run", meta={"universe": body.universe, "strategy": body.strategy, "date": target_str})
    t = threading.Thread(
        target=_run_daily_task,
        args=(job.id, body.universe, body.strategy, target_date),
        daemon=True,
    )
    t.start()

    return {
        "job_id": job.id,
        "status": "running",
        "message": f"Daily run started for universe={body.universe} strategy={body.strategy} date={target_str}",
    }


@router.get("/daily/{job_id}")
def get_daily_run_status(job_id: str) -> dict:
    """Poll the status of a daily run job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Unknown job_id: {job_id}")

    base = {"job_id": job.id, "status": job.status, "started_at": job.started_at}

    if job.status == "running":
        return {**base, "n_done": job.n_done, "n_total": job.n_total, "phase": job.phase}

    if job.status == "error":
        return {**base, "finished_at": job.finished_at, "error": job.error}

    # done
    return {**base, "finished_at": job.finished_at, **(job.result or {})}


# ── Background worker ──────────────────────────────────────────────────────────

def _get_watchlist_symbols_from_db() -> list[str]:
    """Load watchlist symbols from SQLite."""
    try:
        factory = make_session_factory(_DB_PATH)
        with factory() as session:
            entries = session.execute(select(WatchlistEntry)).scalars().all()
            return [e.symbol for e in entries]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load watchlist from DB: %s", exc)
        return []


def _resolve_symbols(universe_name: str) -> list[str]:
    """Return the de-duplicated sorted list of symbols for the requested universe."""
    if universe_name == "watchlist":
        # Prefer DB watchlist; fall back to CSV if DB is empty.
        db_syms = _get_watchlist_symbols_from_db()
        if db_syms:
            return sorted(set(db_syms))
        u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
        return u.watchlist_symbols()

    if universe_name == "sp500":
        sp500 = fetch_sp500_symbols()
        wl_db = _get_watchlist_symbols_from_db()
        return sorted(set(sp500) | set(wl_db))

    if universe_name == "midcap":
        sp400 = fetch_sp400_symbols()
        wl_db = _get_watchlist_symbols_from_db()
        if not wl_db:
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            wl_db = u.watchlist_symbols()
        return sorted(set(sp400) | set(wl_db))

    if universe_name == "smallcap":
        sp600 = fetch_sp600_symbols()
        wl_db = _get_watchlist_symbols_from_db()
        if not wl_db:
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            wl_db = u.watchlist_symbols()
        return sorted(set(sp600) | set(wl_db))

    if universe_name == "nasdaq100":
        ndx = fetch_nasdaq100_symbols()
        wl_db = _get_watchlist_symbols_from_db()
        if not wl_db:
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            wl_db = u.watchlist_symbols()
        return sorted(set(ndx) | set(wl_db))

    # combined = sp500 ∪ sp1000 ∪ watchlist  (sp1000 = sp400 + sp600)
    sp500 = fetch_sp500_symbols()
    sp1000 = fetch_sp1000_symbols()
    wl_db = _get_watchlist_symbols_from_db()
    # Fall back to CSV watchlist if DB is empty.
    if not wl_db:
        u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
        wl_db = u.watchlist_symbols()
    return sorted(set(sp500) | set(sp1000) | set(wl_db))


def _run_daily_task(job_id: str, universe_name: str, strategy_name: str, target_date: date) -> None:
    t0 = _time.monotonic()
    try:
        cfg = load_config(_CONFIG_PATH)
        cfg_hash = config_hash(_CONFIG_PATH)

        symbols = _resolve_symbols(universe_name)
        if not symbols:
            fail_job(job_id, "No symbols found in universe")
            return

        # Load inverse-ETF map once for the whole run (used only for short strategy).
        inverse_map = load_inverse_etf_map() if strategy_name == "short" else {}

        provider = YFinanceProvider()
        cache = ParquetCache(provider)
        end_date = target_date
        start_date = target_date - timedelta(days=_HISTORY_DAYS)
        session_factory = make_session_factory(_DB_PATH)

        successes: list[dict] = []
        errors: list[str] = []

        update_job_progress(job_id, 0, len(symbols), "Starting scan")
        for i, symbol in enumerate(symbols):
            try:
                df = cache.get_daily_bars(symbol, start_date, end_date)
                if df.empty:
                    errors.append(symbol)
                    continue

                results = run_engine(df, cfg, strategy=strategy_name)
                if not results:
                    errors.append(symbol)
                    continue

                target_str = str(target_date)
                bar = next((r for r in reversed(results) if r["date"] == target_str), None)
                if bar is None:
                    bar = results[-1]

                sub_scores = {
                    name: round(comp["sub"], 4)
                    for name, comp in bar["components"].items()
                }

                # Attach inverse ETF for short runs.
                inverse_etf: str | None = None
                if strategy_name == "short":
                    entry = inverse_map.get(symbol)
                    inverse_etf = entry["inverse_etf_symbol"] if entry else None

                successes.append({
                    "symbol": symbol,
                    "date": bar["date"],
                    "composite": bar["composite"],
                    "signal": bar["signal"],
                    "long_allowed": bar["regime"]["long_allowed"],
                    "short_allowed": bar["regime"]["short_allowed"],
                    "sub_scores": sub_scores,
                    "inverse_etf": inverse_etf,
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] daily run error: %s", symbol, exc)
                errors.append(symbol)
            finally:
                update_job_progress(job_id, i + 1, len(symbols), symbol)

        now = datetime.now(timezone.utc)

        with session_factory() as session:
            run = Run(
                run_timestamp=now.isoformat(timespec="seconds"),
                universe=universe_name,
                strategy=strategy_name,
                config_hash=cfg_hash,
                n_symbols=len(symbols),
                n_success=len(successes),
                n_errors=len(errors),
                duration_seconds=round(_time.monotonic() - t0, 2),
            )
            session.add(run)
            session.flush()

            for s in successes:
                session.add(Signal(
                    run_id=run.id,
                    date=s["date"],
                    symbol=s["symbol"],
                    strategy=strategy_name,
                    composite=s["composite"],
                    signal=s["signal"],
                    long_allowed=s["long_allowed"],
                    short_allowed=s["short_allowed"],
                    sub_scores_json=json.dumps(s["sub_scores"]),
                    inverse_etf=s["inverse_etf"],
                ))

            session.commit()
            run_id = run.id

        finish_job(job_id, {
            "run_id": run_id,
            "n_success": len(successes),
            "n_errors": len(errors),
            "universe": universe_name,
            "strategy": strategy_name,
            "date": str(target_date),
        })

    except Exception as exc:  # noqa: BLE001
        logger.exception("Daily run failed for job %s", job_id)
        fail_job(job_id, str(exc))

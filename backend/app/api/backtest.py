"""POST /api/backtest and GET /api/backtest/{job_id} — run & poll backtests."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api.jobs import create_job, fail_job, finish_job, get_job
from backend.app.backtest.engine import run_backtest
from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.universe import Universe
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.db.backtest_models import save_backtest_result
from backend.app.db.models import config_hash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_WATCHLIST_PATH = _REPO_ROOT / "data" / "watchlist.csv"


class BacktestRequest(BaseModel):
    universe: Optional[str] = "watchlist"
    symbols: Optional[list[str]] = None
    start: Optional[str] = None   # YYYY-MM-DD
    end: Optional[str] = None     # YYYY-MM-DD
    initial_account: Optional[float] = None
    slippage_pct: Optional[float] = None
    commission: Optional[float] = None
    strategy: str = "long"        # "long" | "short"


@router.post("", status_code=202)
def start_backtest(body: BacktestRequest) -> dict:
    """Start a backtest in the background. Returns a job_id to poll."""
    cfg = load_config(_CONFIG_PATH)

    # Validate universe / symbols.
    if body.symbols and body.universe:
        # symbols takes precedence when both given.
        universe_name = None
    elif body.symbols:
        universe_name = None
    else:
        universe_name = body.universe or "watchlist"
        if universe_name not in ("watchlist", "sp500", "combined"):
            raise HTTPException(422, detail="universe must be 'watchlist', 'sp500', or 'combined'")

    # Resolve dates.
    end_date = date.fromisoformat(body.end) if body.end else date.today()
    if body.start:
        start_date = date.fromisoformat(body.start)
    else:
        start_date = end_date - timedelta(days=cfg.backtest.start_years_back * 365)

    if start_date >= end_date:
        raise HTTPException(422, detail="start must be before end")

    if body.strategy not in ("long", "short"):
        raise HTTPException(422, detail="strategy must be 'long' or 'short'")

    msg = (
        f"Backtest started: {universe_name or 'custom'} "
        f"{start_date} → {end_date} strategy={body.strategy}"
    )

    job = create_job("backtest", meta={
        "universe": universe_name,
        "start": str(start_date),
        "end": str(end_date),
        "strategy": body.strategy,
    })

    t = threading.Thread(
        target=_run_backtest_task,
        args=(job.id, body, universe_name, start_date, end_date, body.strategy),
        daemon=True,
    )
    t.start()

    return {"job_id": job.id, "status": "running", "message": msg}


@router.get("/{job_id}")
def get_backtest_status(job_id: str) -> dict:
    """Poll status or retrieve the full result of a backtest job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Unknown job_id: {job_id}")

    base = {"job_id": job.id, "status": job.status, "started_at": job.started_at}

    if job.status == "running":
        return base

    if job.status == "error":
        return {**base, "finished_at": job.finished_at, "error": job.error}

    # done
    return {**base, "finished_at": job.finished_at, **(job.result or {})}


# ── Background worker ──────────────────────────────────────────────────────────

def _run_backtest_task(
    job_id: str,
    body: BacktestRequest,
    universe_name: str | None,
    start: date,
    end: date,
    strategy: str = "long",
) -> None:
    try:
        cfg = load_config(_CONFIG_PATH)

        # Resolve symbols.
        if body.symbols:
            symbols = [s.upper() for s in body.symbols]
        elif universe_name == "watchlist":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            symbols = u.watchlist_symbols()
        else:
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=True)
            symbols = u.symbols

        if not symbols:
            fail_job(job_id, "No symbols resolved for backtest")
            return

        cache = ParquetCache(YFinanceProvider())

        def fetcher(sym: str, s: date, e: date):
            return cache.get_daily_bars(sym, s, e)

        t0 = time.perf_counter()
        result = run_backtest(
            symbols=symbols,
            start=start,
            end=end,
            cfg=cfg,
            data_fetcher=fetcher,
            strategy=strategy,
            initial_account=body.initial_account,
            slippage_pct=body.slippage_pct,
            commission=body.commission,
        )
        duration = time.perf_counter() - t0

        cfg_hash = config_hash(_CONFIG_PATH)
        db_run_id = save_backtest_result(result, cfg_hash, duration)

        payload: dict = {
            "db_run_id": db_run_id,
            "duration_seconds": round(duration, 2),
            "params": result.params,
            "metrics": result.metrics,
            "equity_curve": result.equity_curve,
            "trades": [asdict(t) for t in result.trades],
            "survivorship_note": result.survivorship_note,
            "strategy": strategy,
        }
        if result.coverage_report is not None:
            payload["coverage_report"] = result.coverage_report.to_dict()

        finish_job(job_id, payload)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Backtest failed for job %s", job_id)
        fail_job(job_id, str(exc))

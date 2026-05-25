"""POST /api/backtest and GET /api/backtest/{job_id} — run & poll backtests.

MOD-F: accepts full portfolio-management params; returns strategy metrics,
benchmark metrics, side-by-side comparison, both equity curves, fee-inclusive
trade log, and slot-vs-capital constraint counts.
"""
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

from backend.app.api.jobs import create_job, fail_job, finish_job, get_job, update_job_progress
from backend.app.backtest.engine import run_backtest
from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.universe import Universe, fetch_nasdaq100_symbols, fetch_sp400_symbols, fetch_sp600_symbols
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
    strategy: str = "long"        # "long" | "short"
    # MOD-F params (all optional; fall back to config.yaml defaults)
    initial_fund: Optional[float] = None
    initial_account: Optional[float] = None  # backward-compat alias for initial_fund
    slippage_pct: Optional[float] = None
    fee_per_share: Optional[float] = None
    fee_min: Optional[float] = None
    fee_max_pct_of_trade: Optional[float] = None
    position_size_pct: Optional[float] = None
    position_size_min: Optional[float] = None
    atr_stop_multiple: Optional[float] = None
    atr_period: Optional[int] = None
    max_concurrent_positions: Optional[int] = None
    per_name_cap_pct: Optional[float] = None
    top_n: Optional[int] = None
    benchmark_symbol: Optional[str] = None
    risk_free_rate: Optional[float] = None
    # Legacy flat-commission param (ignored when fee_* params are provided)
    commission: Optional[float] = None


@router.post("", status_code=202)
def start_backtest(body: BacktestRequest) -> dict:
    """Start a backtest in the background. Returns a job_id to poll."""
    cfg = load_config(_CONFIG_PATH)

    if body.symbols and body.universe:
        universe_name = None
    elif body.symbols:
        universe_name = None
    else:
        universe_name = body.universe or "watchlist"
        if universe_name not in ("watchlist", "sp500", "combined", "midcap", "smallcap", "nasdaq100"):
            raise HTTPException(
                422,
                detail="universe must be 'watchlist', 'sp500', 'combined', 'midcap', 'smallcap', or 'nasdaq100'",
            )

    end_date = date.fromisoformat(body.end) if body.end else date.today()
    if body.start:
        start_date = date.fromisoformat(body.start)
    else:
        start_date = end_date - timedelta(days=cfg.backtest.start_years_back * 365)

    if start_date >= end_date:
        raise HTTPException(422, detail="start must be before end")

    if body.strategy not in ("long", "short"):
        raise HTTPException(422, detail="strategy must be 'long' or 'short'")

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

    return {
        "job_id": job.id,
        "status": "running",
        "message": (
            f"Backtest started: {universe_name or 'custom'} "
            f"{start_date} → {end_date} strategy={body.strategy}"
        ),
    }


@router.get("/{job_id}")
def get_backtest_status(job_id: str) -> dict:
    """Poll status or retrieve the full MOD-F result of a backtest job.

    Done response includes:
      status, strategy_metrics, benchmark_metrics, comparison,
      equity_curve (strategy), benchmark_equity_curve,
      trades (fee-inclusive), constraint_counts, params,
      coverage_report (short runs only).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Unknown job_id: {job_id}")

    base = {"job_id": job.id, "status": job.status, "started_at": job.started_at}

    if job.status == "running":
        return {**base, "n_done": job.n_done, "n_total": job.n_total, "phase": job.phase}

    if job.status == "error":
        return {**base, "finished_at": job.finished_at, "error": job.error}

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

        if body.symbols:
            symbols = [s.upper() for s in body.symbols]
        elif universe_name == "watchlist":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            symbols = u.watchlist_symbols()
        elif universe_name == "midcap":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            wl = u.watchlist_symbols()
            symbols = sorted(set(fetch_sp400_symbols()) | set(wl))
        elif universe_name == "smallcap":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            wl = u.watchlist_symbols()
            symbols = sorted(set(fetch_sp600_symbols()) | set(wl))
        elif universe_name == "nasdaq100":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            wl = u.watchlist_symbols()
            symbols = sorted(set(fetch_nasdaq100_symbols()) | set(wl))
        elif universe_name == "combined":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=True, include_sp1000=True)
            symbols = u.symbols
        else:  # sp500
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=True)
            symbols = u.symbols

        if not symbols:
            fail_job(job_id, "No symbols resolved for backtest")
            return

        cache = ParquetCache(YFinanceProvider())

        def fetcher(sym: str, s: date, e: date):
            return cache.get_daily_bars(sym, s, e)

        update_job_progress(job_id, 0, len(symbols), "Loading data")

        def _progress_cb(n_done: int, n_total: int, phase: str) -> None:
            update_job_progress(job_id, n_done, n_total, phase)

        # Resolve initial_fund (support both new and legacy field name)
        eff_initial_fund = body.initial_fund or body.initial_account

        t0 = time.perf_counter()
        result = run_backtest(
            symbols=symbols,
            start=start,
            end=end,
            cfg=cfg,
            data_fetcher=fetcher,
            strategy=strategy,
            initial_fund=eff_initial_fund,
            slippage_pct=body.slippage_pct,
            fee_per_share=body.fee_per_share,
            fee_min=body.fee_min,
            fee_max_pct_of_trade=body.fee_max_pct_of_trade,
            position_size_pct=body.position_size_pct,
            position_size_min=body.position_size_min,
            atr_stop_multiple=body.atr_stop_multiple,
            atr_period=body.atr_period,
            max_concurrent_positions=body.max_concurrent_positions,
            per_name_cap_pct=body.per_name_cap_pct,
            top_n=body.top_n,
            benchmark_symbol=body.benchmark_symbol,
            risk_free_rate=body.risk_free_rate,
            progress_callback=_progress_cb,
        )
        duration = time.perf_counter() - t0

        cfg_hash = config_hash(_CONFIG_PATH)
        db_run_id = save_backtest_result(result, cfg_hash, duration)

        payload: dict = {
            "db_run_id": db_run_id,
            "duration_seconds": round(duration, 2),
            "params": result.params,
            # MOD-F: split into strategy_metrics + benchmark_metrics + comparison
            "strategy_metrics": result.metrics,
            "benchmark_metrics": result.benchmark_metrics,
            "comparison": result.comparison,
            # Legacy key (backward-compat; same as strategy_metrics)
            "metrics": result.metrics,
            "equity_curve": result.equity_curve,
            "benchmark_equity_curve": result.benchmark_equity_curve,
            "trades": [asdict(t) for t in result.trades],
            "constraint_counts": result.constraint_counts,
            "survivorship_note": result.survivorship_note,
            "strategy": strategy,
        }
        if result.coverage_report is not None:
            payload["coverage_report"] = result.coverage_report.to_dict()

        finish_job(job_id, payload)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Backtest failed for job %s", job_id)
        fail_job(job_id, str(exc))

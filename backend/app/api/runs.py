"""POST /api/runs/daily and GET /api/runs/daily/{job_id} — trigger & poll daily runs."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api.jobs import create_job, fail_job, finish_job, get_job
from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.universe import Universe
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.db.models import Run, Signal, config_hash, make_session_factory
from backend.app.scoring.composite import run_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_DATA_DIR = _REPO_ROOT.parent / "data"
_DB_PATH = _DATA_DIR / "signals.db"
_WATCHLIST_PATH = _REPO_ROOT / "data" / "watchlist.csv"
_HISTORY_DAYS = 400


class DailyRunRequest(BaseModel):
    universe: str = "watchlist"
    date: str | None = None


@router.post("/daily", status_code=202)
def trigger_daily_run(body: DailyRunRequest) -> dict:
    """Trigger a background daily signal run."""
    if body.universe not in ("watchlist", "sp500"):
        raise HTTPException(422, detail="universe must be 'watchlist' or 'sp500'")

    target_str = body.date or str(date.today())
    try:
        target_date = date.fromisoformat(target_str)
    except ValueError:
        raise HTTPException(422, detail="date must be YYYY-MM-DD")

    job = create_job("daily_run", meta={"universe": body.universe, "date": target_str})
    t = threading.Thread(
        target=_run_daily_task,
        args=(job.id, body.universe, target_date),
        daemon=True,
    )
    t.start()

    return {
        "job_id": job.id,
        "status": "running",
        "message": f"Daily run started for universe={body.universe} date={target_str}",
    }


@router.get("/daily/{job_id}")
def get_daily_run_status(job_id: str) -> dict:
    """Poll the status of a daily run job."""
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

def _run_daily_task(job_id: str, universe_name: str, target_date: date) -> None:
    try:
        cfg = load_config(_CONFIG_PATH)
        cfg_hash = config_hash(_CONFIG_PATH)

        if universe_name == "watchlist":
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
            symbols = u.watchlist_symbols()
        else:
            u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=True)
            symbols = u.symbols

        if not symbols:
            fail_job(job_id, "No symbols found in universe")
            return

        provider = YFinanceProvider()
        cache = ParquetCache(provider)
        end_date = target_date
        start_date = target_date - timedelta(days=_HISTORY_DAYS)
        session_factory = make_session_factory(_DB_PATH)

        successes: list[dict] = []
        errors: list[str] = []

        for symbol in symbols:
            try:
                df = cache.get_daily_bars(symbol, start_date, end_date)
                if df.empty:
                    errors.append(symbol)
                    continue

                results = run_engine(df, cfg)
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
                successes.append({
                    "symbol": symbol,
                    "date": bar["date"],
                    "composite": bar["composite"],
                    "signal": bar["signal"],
                    "long_allowed": bar["regime"]["long_allowed"],
                    "short_allowed": bar["regime"]["short_allowed"],
                    "sub_scores": sub_scores,
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] daily run error: %s", symbol, exc)
                errors.append(symbol)

        now = datetime.now(timezone.utc)
        import time as _time
        t0 = _time.monotonic()

        with session_factory() as session:
            run = Run(
                run_timestamp=now.isoformat(timespec="seconds"),
                universe=universe_name,
                config_hash=cfg_hash,
                n_symbols=len(symbols),
                n_success=len(successes),
                n_errors=len(errors),
                duration_seconds=round(_time.monotonic() - t0 + 0.001, 2),
            )
            session.add(run)
            session.flush()

            for s in successes:
                session.add(Signal(
                    run_id=run.id,
                    date=s["date"],
                    symbol=s["symbol"],
                    composite=s["composite"],
                    signal=s["signal"],
                    long_allowed=s["long_allowed"],
                    short_allowed=s["short_allowed"],
                    sub_scores_json=json.dumps(s["sub_scores"]),
                ))

            session.commit()
            run_id = run.id

        finish_job(job_id, {
            "run_id": run_id,
            "n_success": len(successes),
            "n_errors": len(errors),
            "universe": universe_name,
            "date": str(target_date),
        })

    except Exception as exc:  # noqa: BLE001
        logger.exception("Daily run failed for job %s", job_id)
        fail_job(job_id, str(exc))

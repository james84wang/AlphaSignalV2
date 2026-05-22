"""GET /api/symbols/{symbol}/bars and GET /api/symbols/{symbol}/signal."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.db.models import Signal, Run, make_session_factory
from backend.app.scoring.composite import run_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/symbols", tags=["symbols"])

_SESSION = make_session_factory()

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WATCHLIST_PATH = _REPO_ROOT / "data" / "watchlist.csv"
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

# Bars of history required to warm up EMA200.
_WARMUP_DAYS = 400

_RANGE_DAYS: dict[str, int] = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


def _get_cache() -> ParquetCache:
    return ParquetCache(YFinanceProvider())


@router.get("/{symbol}/bars")
def get_bars(
    symbol: str,
    range: str = Query("1y", description="1m | 3m | 6m | 1y | 2y | 5y"),
) -> dict:
    """Return OHLCV bars in lightweight-charts format."""
    symbol = symbol.upper()

    if range not in _RANGE_DAYS:
        raise HTTPException(422, detail=f"range must be one of: {list(_RANGE_DAYS)}")

    n_days = _RANGE_DAYS[range]
    end = date.today()
    start = end - timedelta(days=n_days)

    cache = _get_cache()
    try:
        df = cache.get_daily_bars(symbol, start, end)
    except Exception as exc:
        logger.warning("[%s] bars fetch failed: %s", symbol, exc)
        raise HTTPException(404, detail=f"No data found for symbol {symbol}")

    if df.empty:
        raise HTTPException(404, detail=f"No data found for symbol {symbol}")

    bars = [
        {
            "time": str(idx.date()) if hasattr(idx, "date") else str(idx),
            "open": round(float(row["open"]), 4),
            "high": round(float(row["high"]), 4),
            "low": round(float(row["low"]), 4),
            "close": round(float(row["close"]), 4),
            "volume": int(row["volume"]),
        }
        for idx, row in df.iterrows()
    ]

    return {
        "symbol": symbol,
        "range": range,
        "start": str(start),
        "end": str(end),
        "n_bars": len(bars),
        "bars": bars,
    }


@router.get("/{symbol}/signal")
def get_signal(
    symbol: str,
    date_param: str | None = Query(None, alias="date", description="YYYY-MM-DD"),
) -> dict:
    """Return full audit object (all sub-scores) for a symbol on a given date."""
    symbol = symbol.upper()
    target_str = date_param or str(date.today())

    try:
        target_date = date.fromisoformat(target_str)
    except ValueError:
        raise HTTPException(422, detail="date must be YYYY-MM-DD")

    # Try DB first.
    with _SESSION() as session:
        row = (
            session.query(Signal)
            .join(Run)
            .filter(Signal.symbol == symbol, Signal.date == target_str)
            .order_by(desc(Run.id))
            .first()
        )

    if row is not None:
        sub_scores = json.loads(row.sub_scores_json)
        cfg = load_config(_CONFIG_PATH)
        components = {
            name: {
                "sub": sub_scores.get(name, 0.0),
                "weight": float(getattr(cfg.weights, name)),
                "weighted": round(sub_scores.get(name, 0.0) * float(getattr(cfg.weights, name)) / 100.0, 6),
            }
            for name in ("candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi")
        }
        return {
            "symbol": symbol,
            "date": row.date,
            "composite": round(row.composite, 4),
            "signal": row.signal,
            "source": "db",
            "regime": {"long_allowed": row.long_allowed, "short_allowed": row.short_allowed},
            "components": components,
        }

    # Recompute on-the-fly.
    end = target_date
    start = target_date - timedelta(days=_WARMUP_DAYS)
    cache = _get_cache()
    cfg = load_config(_CONFIG_PATH)

    try:
        df = cache.get_daily_bars(symbol, start, end)
    except Exception as exc:
        logger.warning("[%s] recompute fetch failed: %s", symbol, exc)
        raise HTTPException(404, detail=f"No data for {symbol}")

    if df.empty:
        raise HTTPException(404, detail=f"No data for {symbol}")

    results = run_engine(df, cfg)
    bar = next((r for r in reversed(results) if r["date"] == target_str), None)
    if bar is None:
        bar = results[-1] if results else None
    if bar is None:
        raise HTTPException(404, detail=f"No signal computed for {symbol} on {target_str}")

    return {
        "symbol": symbol,
        "date": bar["date"],
        "composite": round(bar["composite"], 4),
        "signal": bar["signal"],
        "source": "computed",
        "regime": bar["regime"],
        "components": bar["components"],
    }

"""GET /api/signals — ranked signal table from the latest daily run."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from backend.app.db.models import Run, Signal, make_session_factory

router = APIRouter(prefix="/api/signals", tags=["signals"])

_SESSION = make_session_factory()


_VALID_UNIVERSES = ("watchlist", "sp500", "combined", "midcap", "smallcap", "nasdaq100")


@router.get("")
def get_signals(
    date_param: str | None = Query(None, alias="date", description="YYYY-MM-DD"),
    universe: str = Query("combined", description="watchlist | sp500 | combined | midcap | smallcap | nasdaq100"),
) -> dict:
    """Return the ranked signal table from the most recent run matching the filters."""
    if universe not in _VALID_UNIVERSES:
        raise HTTPException(422, detail=f"universe must be one of {_VALID_UNIVERSES}")

    with _SESSION() as session:
        q = session.query(Run).filter(Run.universe == universe).order_by(desc(Run.id))

        if date_param:
            try:
                date.fromisoformat(date_param)
            except ValueError:
                raise HTTPException(422, detail="date must be YYYY-MM-DD")
            # Find the most recent run that has at least one signal for this date.
            matching_ids = (
                session.query(Signal.run_id)
                .filter(Signal.date == date_param)
                .distinct()
                .subquery()
            )
            q = q.filter(Run.id.in_(matching_ids))

        run = q.first()
        if run is None:
            raise HTTPException(404, detail="No runs found for the given filters")

        signals_q = session.query(Signal).filter(Signal.run_id == run.id)
        if date_param:
            signals_q = signals_q.filter(Signal.date == date_param)

        rows = signals_q.all()

    ranked = sorted(rows, key=lambda s: s.composite, reverse=True)
    signal_date = ranked[0].date if ranked else (date_param or "")

    return {
        "run_id": run.id,
        "run_timestamp": run.run_timestamp,
        "date": signal_date,
        "universe": run.universe,
        "config_hash": run.config_hash,
        "n_signals": len(ranked),
        "signals": [
            {
                "rank": i + 1,
                "symbol": s.symbol,
                "composite": round(s.composite, 4),
                "signal": s.signal,
                "long_allowed": s.long_allowed,
                "short_allowed": s.short_allowed,
                "sub_scores": json.loads(s.sub_scores_json),
            }
            for i, s in enumerate(ranked)
        ],
    }

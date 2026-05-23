"""GET /api/market/overview — live market sentiment snapshot."""
from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.data.market_overview import get_market_overview

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/overview")
def market_overview(refresh: bool = Query(default=False, description="Force cache refresh")) -> dict:
    """Return the latest quote for each market index/ETF plus the CNN Fear & Greed score.

    Data is cached for ~15 minutes. Individual tiles may show status='unavailable'
    if a feed is temporarily down — this never causes a 500 error.
    """
    return get_market_overview(force_refresh=refresh)

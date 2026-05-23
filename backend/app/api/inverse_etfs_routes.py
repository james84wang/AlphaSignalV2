"""GET /api/inverse-etfs — return the current inverse-ETF mapping."""
from __future__ import annotations

from fastapi import APIRouter

from backend.app.data.inverse_etfs import load_inverse_etf_map

router = APIRouter(prefix="/api/inverse-etfs", tags=["inverse-etfs"])


@router.get("")
def get_inverse_etfs() -> dict:
    """Return the current inverse-ETF map loaded from data/inverse_etfs.csv."""
    mapping = load_inverse_etf_map()
    return {
        "count": len(mapping),
        "map": mapping,
    }

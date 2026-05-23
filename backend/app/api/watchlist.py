"""Watchlist CRUD endpoints.

GET  /api/watchlist            — list all watchlist symbols
POST /api/watchlist            — add a symbol
DELETE /api/watchlist/{symbol} — remove a symbol

Symbols are persisted in SQLite (watchlist table). The data/watchlist.csv
file is used as a one-time seed (see main.py startup event).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.app.db.models import WatchlistEntry, make_session_factory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PATH = _REPO_ROOT.parent / "data" / "signals.db"

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _session_factory():
    return make_session_factory(_DB_PATH)


class WatchlistAddRequest(BaseModel):
    symbol: str
    note: str | None = None


@router.get("")
def list_watchlist() -> dict:
    """Return all symbols in the watchlist."""
    factory = _session_factory()
    with factory() as session:
        entries = session.execute(
            select(WatchlistEntry).order_by(WatchlistEntry.added_at)
        ).scalars().all()
        return {
            "count": len(entries),
            "symbols": [
                {"symbol": e.symbol, "added_at": e.added_at, "note": e.note}
                for e in entries
            ],
        }


@router.post("", status_code=201)
def add_watchlist_symbol(body: WatchlistAddRequest) -> dict:
    """Add a symbol to the watchlist."""
    sym = body.symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(422, detail=f"Invalid symbol format: {sym!r}. Use 1–10 uppercase letters/digits.")

    factory = _session_factory()
    with factory() as session:
        existing = session.execute(
            select(WatchlistEntry).where(WatchlistEntry.symbol == sym)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(409, detail=f"{sym} is already in the watchlist.")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = WatchlistEntry(symbol=sym, added_at=now, note=body.note)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return {"symbol": entry.symbol, "added_at": entry.added_at, "note": entry.note}


@router.delete("/{symbol}", status_code=200)
def remove_watchlist_symbol(symbol: str) -> dict:
    """Remove a symbol from the watchlist."""
    sym = symbol.strip().upper()
    factory = _session_factory()
    with factory() as session:
        entry = session.execute(
            select(WatchlistEntry).where(WatchlistEntry.symbol == sym)
        ).scalar_one_or_none()
        if entry is None:
            raise HTTPException(404, detail=f"{sym} not found in watchlist.")
        session.delete(entry)
        session.commit()
        return {"ok": True, "symbol": sym}

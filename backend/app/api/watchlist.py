"""Watchlist CRUD endpoints (multi-list).

GET    /api/watchlists                          — all configured lists + their symbols
POST   /api/watchlists/{list_name}/symbols      — add a symbol to a list
DELETE /api/watchlists/{list_name}/symbols/{sym} — remove a symbol from a list
GET    /api/watchlist                           — legacy: the default list only

Lists are defined by ``universe.watchlists`` in config.yaml. Symbols are
persisted in SQLite (watchlist table, keyed by (list_name, symbol)).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.app.config import load_config
from backend.app.data.watchlists import DEFAULT_LIST, list_names
from backend.app.db.models import WatchlistEntry, make_session_factory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["watchlist"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class WatchlistAddRequest(BaseModel):
    symbol: str
    note: str | None = None


def _configured_names() -> list[str]:
    return list_names(load_config(_CONFIG_PATH))


def _validate_list(list_name: str) -> None:
    if list_name not in _configured_names():
        raise HTTPException(404, detail=f"Unknown watchlist {list_name!r}")


def _entries_for(session, list_name: str) -> list[dict]:
    rows = session.execute(
        select(WatchlistEntry)
        .where(WatchlistEntry.list_name == list_name)
        .order_by(WatchlistEntry.added_at)
    ).scalars().all()
    return [{"symbol": e.symbol, "added_at": e.added_at, "note": e.note} for e in rows]


@router.get("/watchlists")
def list_all_watchlists() -> dict:
    """Return every configured list with its symbols (empty lists included)."""
    factory = make_session_factory()
    with factory() as session:
        lists = [
            {"name": name, "symbols": (syms := _entries_for(session, name)), "count": len(syms)}
            for name in _configured_names()
        ]
    return {"lists": lists}


@router.post("/watchlists/{list_name}/symbols", status_code=201)
def add_symbol(list_name: str, body: WatchlistAddRequest) -> dict:
    """Add a symbol to a named list."""
    _validate_list(list_name)
    sym = body.symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(422, detail=f"Invalid symbol format: {sym!r}. Use 1–10 uppercase letters/digits.")

    factory = make_session_factory()
    with factory() as session:
        existing = session.execute(
            select(WatchlistEntry).where(
                WatchlistEntry.list_name == list_name, WatchlistEntry.symbol == sym
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(409, detail=f"{sym} is already in {list_name}.")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = WatchlistEntry(list_name=list_name, symbol=sym, added_at=now, note=body.note)
        session.add(entry)
        session.commit()
        return {"list_name": list_name, "symbol": sym, "added_at": now, "note": body.note}


@router.delete("/watchlists/{list_name}/symbols/{symbol}", status_code=200)
def remove_symbol(list_name: str, symbol: str) -> dict:
    """Remove a symbol from a named list."""
    _validate_list(list_name)
    sym = symbol.strip().upper()
    factory = make_session_factory()
    with factory() as session:
        entry = session.execute(
            select(WatchlistEntry).where(
                WatchlistEntry.list_name == list_name, WatchlistEntry.symbol == sym
            )
        ).scalar_one_or_none()
        if entry is None:
            raise HTTPException(404, detail=f"{sym} not found in {list_name}.")
        session.delete(entry)
        session.commit()
        return {"ok": True, "list_name": list_name, "symbol": sym}


@router.get("/watchlist")
def list_default_watchlist() -> dict:
    """Legacy endpoint: the default list only ({count, symbols})."""
    factory = make_session_factory()
    with factory() as session:
        syms = _entries_for(session, DEFAULT_LIST)
    return {"count": len(syms), "symbols": syms}

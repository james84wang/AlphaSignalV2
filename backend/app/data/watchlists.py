"""Watchlist + trading-universe resolution.

Central place that turns a universe identifier (from the Dashboard/Backtest UI)
into a concrete list of symbols. Supports several named watchlists, all of which
are part of the trading universe.

Universe identifiers
---------------------
- ``wl:<name>``  → exactly the symbols in that one watchlist.
- ``watchlist``  → the union of every configured watchlist.
- ``sp500`` | ``midcap`` | ``smallcap`` | ``nasdaq100`` | ``combined``
                 → the index membership ∪ every watchlist.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.app.config import AppConfig
from backend.app.data.universe import (
    fetch_nasdaq100_symbols,
    fetch_sp400_symbols,
    fetch_sp500_symbols,
    fetch_sp600_symbols,
    fetch_sp1000_symbols,
)
from backend.app.db.models import WatchlistEntry, make_session_factory

logger = logging.getLogger(__name__)

WL_PREFIX = "wl:"
DEFAULT_LIST = "Watchlist"
INDEX_UNIVERSES = ("sp500", "midcap", "smallcap", "nasdaq100", "combined")


def list_names(cfg: AppConfig) -> list[str]:
    """Return the configured watchlist names (falls back to a single default)."""
    names = list(cfg.universe.watchlists)
    return names or [DEFAULT_LIST]


def get_watchlist_symbols(list_name: str | None = None) -> list[str]:
    """Symbols for one watchlist, or the union of all when ``list_name`` is None."""
    try:
        factory = make_session_factory()
        with factory() as session:
            q = select(WatchlistEntry)
            if list_name is not None:
                q = q.where(WatchlistEntry.list_name == list_name)
            rows = session.execute(q).scalars().all()
        return sorted({r.symbol for r in rows})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read watchlist(s) from DB: %s", exc)
        return []


def is_valid_universe(name: str, cfg: AppConfig) -> bool:
    if name == "watchlist" or name in INDEX_UNIVERSES:
        return True
    if name.startswith(WL_PREFIX):
        return name[len(WL_PREFIX):] in list_names(cfg)
    return False


def resolve_universe(name: str, cfg: AppConfig) -> list[str]:
    """Resolve a universe identifier into a de-duplicated, sorted symbol list."""
    if name.startswith(WL_PREFIX):
        return get_watchlist_symbols(name[len(WL_PREFIX):])

    all_watchlist = set(get_watchlist_symbols(None))

    if name == "watchlist":
        return sorted(all_watchlist)

    if name == "sp500":
        idx = set(fetch_sp500_symbols())
    elif name == "midcap":
        idx = set(fetch_sp400_symbols())
    elif name == "smallcap":
        idx = set(fetch_sp600_symbols())
    elif name == "nasdaq100":
        idx = set(fetch_nasdaq100_symbols())
    elif name == "combined":
        idx = set(fetch_sp500_symbols()) | set(fetch_sp1000_symbols())
    else:
        raise ValueError(f"Unknown universe {name!r}")

    return sorted(idx | all_watchlist)

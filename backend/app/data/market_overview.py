"""Market overview data service: index/ETF quotes + CNN Fear & Greed Index.

Caches results for _CACHE_TTL seconds (15 min) to respect rate limits.
All failures are caught and returned as {"status": "unavailable"} so a
broken scrape can never crash the dashboard.

Ticker choices verified against Yahoo Finance:
    ^GSPC  S&P 500
    ^IXIC  NASDAQ Composite
    ^NDX   NASDAQ 100
    ^VIX   CBOE Volatility Index
    XLK    Technology Select Sector SPDR ETF
    ^SP400 S&P MidCap 400  (^SP600 used for SmallCap 600; no free feed for the
    ^SP600 S&P SmallCap 600  combined "S&P 1000", so they are shown separately)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_TTL = 900  # 15 minutes

_TICKERS: list[dict[str, str]] = [
    {"key": "sp500",    "symbol": "^GSPC",  "label": "S&P 500"},
    {"key": "nasdaq",   "symbol": "^IXIC",  "label": "NASDAQ Composite"},
    {"key": "ndx100",   "symbol": "^NDX",   "label": "NASDAQ 100"},
    {"key": "vix",      "symbol": "^VIX",   "label": "VIX"},
    {"key": "xlk",      "symbol": "XLK",    "label": "Tech Sector (XLK)"},
    {"key": "midcap",   "symbol": "^SP400", "label": "S&P MidCap 400"},
    {"key": "smallcap", "symbol": "^SP600", "label": "S&P SmallCap 600"},
]

_CNN_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_CNN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
}

# CNN returns a lower-case 'rating' field; map it to a display label.
_RATING_MAP = {
    "extreme fear": "Extreme Fear",
    "fear": "Fear",
    "neutral": "Neutral",
    "greed": "Greed",
    "extreme greed": "Extreme Greed",
}


@dataclass
class _OverviewCache:
    data: dict | None = None
    fetched_at: float = 0.0


_cache = _OverviewCache()


def _fetch_quote(symbol: str) -> dict:
    """Return last price and daily % change for one ticker, or {status: unavailable}."""
    try:
        fi = yf.Ticker(symbol).fast_info
        last: float | None = getattr(fi, "last_price", None)
        prev: float | None = getattr(fi, "previous_close", None)
        if last is None:
            return {"status": "unavailable"}
        change_pct = round((last - prev) / prev * 100, 2) if prev else None
        return {
            "status": "ok",
            "last": round(last, 4),
            "prev_close": round(prev, 4) if prev is not None else None,
            "change_pct": change_pct,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[market_overview] %s fetch failed: %s", symbol, exc)
        return {"status": "unavailable"}


def _fetch_fear_and_greed() -> dict:
    """Fetch CNN Fear & Greed Index, failing gracefully if unavailable.

    Source: CNN's undocumented dataviz JSON endpoint. Requires a browser-like
    User-Agent + Referer. Falls back to {"status": "unavailable"} on any error.
    """
    try:
        resp = httpx.get(_CNN_FNG_URL, headers=_CNN_HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score")
        rating_raw: str = fg.get("rating", "")
        label = _RATING_MAP.get(rating_raw.lower(), rating_raw.title())
        if score is None:
            return {"status": "unavailable"}
        return {
            "status": "ok",
            "score": round(float(score), 1),
            "rating": label,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[market_overview] CNN Fear & Greed fetch failed: %s", exc)
        return {"status": "unavailable"}


def get_market_overview(force_refresh: bool = False) -> dict:
    """Return a cached market overview dict, refreshing if the cache is stale."""
    now = time.monotonic()
    if (
        not force_refresh
        and _cache.data is not None
        and (now - _cache.fetched_at) < _CACHE_TTL
    ):
        return _cache.data

    indices: dict[str, dict] = {}
    for cfg in _TICKERS:
        indices[cfg["key"]] = {
            "label": cfg["label"],
            "symbol": cfg["symbol"],
            **_fetch_quote(cfg["symbol"]),
        }

    result = {
        "indices": indices,
        "fear_and_greed": {
            "label": "CNN Fear & Greed Index",
            "source": "production.dataviz.cnn.io",
            **_fetch_fear_and_greed(),
        },
        "cache_ttl_seconds": _CACHE_TTL,
        "note": (
            "S&P MidCap 400 (^SP400) and S&P SmallCap 600 (^SP600) are shown "
            "separately — no single free-feed ticker exists for the combined S&P 1000."
        ),
    }

    _cache.data = result
    _cache.fetched_at = now
    return result

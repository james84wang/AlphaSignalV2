"""Universe and watchlist management.

Sources (in priority order):
1. User watchlist:    SQLite watchlist table (seeded from data/watchlist.csv on first run)
2. Built-in S&P 500:  fetched once from Wikipedia, cached at data/sp500.csv
3. S&P 1000:          S&P MidCap 400 + S&P SmallCap 600, each cached separately
4. Combined universe: sp500 ∪ sp1000 ∪ watchlist, de-duplicated (default)
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DATA_DIR = _REPO_ROOT / "data"
_SP500_CACHE    = _DATA_DIR / "sp500.csv"
_SP400_CACHE    = _DATA_DIR / "sp400.csv"
_SP600_CACHE    = _DATA_DIR / "sp600.csv"
_NASDAQ100_CACHE = _DATA_DIR / "nasdaq100.csv"

_SP500_WIKI_URL    = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_SP400_WIKI_URL    = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
_SP600_WIKI_URL    = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
_NASDAQ100_WIKI_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _fetch_html(url: str) -> str:
    """Fetch URL with a browser-like User-Agent to avoid Wikipedia 403s."""
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _fetch_wiki_symbols(url: str, cache_path: Path, label: str, force_refresh: bool = False) -> list[str]:
    """Generic Wikipedia constituent-table fetcher with local cache."""
    _ensure_data_dir()

    if cache_path.exists() and not force_refresh:
        df = pd.read_csv(cache_path)
        symbols = df["symbol"].str.upper().tolist()
        logger.debug("Loaded %d %s symbols from cache", len(symbols), label)
        return symbols

    logger.info("Fetching %s list from Wikipedia…", label)
    try:
        html = _fetch_html(url)
        # Try named table id first ("constituents"), then fall back to first table.
        try:
            tables = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})
        except ValueError:
            tables = pd.read_html(io.StringIO(html))

        df_raw = tables[0]

        # Wikipedia columns may be "Symbol", "Ticker symbol", etc.
        sym_col = next(
            (c for c in df_raw.columns if "symbol" in str(c).lower() or "ticker" in str(c).lower()),
            df_raw.columns[0],
        )
        df = pd.DataFrame({"symbol": df_raw[sym_col].astype(str).str.replace(".", "-", regex=False).str.upper()})
        df = df[df["symbol"].str.match(r"^[A-Z][A-Z0-9.\-]{0,9}$")]  # sanity-check symbols
        df.to_csv(cache_path, index=False)
        symbols = df["symbol"].tolist()
        logger.info("Cached %d %s symbols to %s", len(symbols), label, cache_path)
        return symbols
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch %s list: %s", label, exc)
        if cache_path.exists():
            df = pd.read_csv(cache_path)
            return df["symbol"].str.upper().tolist()
        return []


def fetch_sp500_symbols(force_refresh: bool = False) -> list[str]:
    """Return S&P 500 ticker symbols, fetching from Wikipedia once and caching."""
    _ensure_data_dir()

    if _SP500_CACHE.exists() and not force_refresh:
        df = pd.read_csv(_SP500_CACHE)
        symbols = df["symbol"].str.upper().tolist()
        logger.debug("Loaded %d S&P 500 symbols from cache", len(symbols))
        return symbols

    logger.info("Fetching S&P 500 list from Wikipedia…")
    try:
        html = _fetch_html(_SP500_WIKI_URL)
        tables = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})
        df = tables[0][["Symbol", "GICS Sector"]].copy()
        df.columns = ["symbol", "sector"]
        df["symbol"] = df["symbol"].str.replace(".", "-", regex=False).str.upper()
        df["exchange"] = "NYSE/NASDAQ"
        df.to_csv(_SP500_CACHE, index=False)
        symbols = df["symbol"].tolist()
        logger.info("Cached %d S&P 500 symbols to %s", len(symbols), _SP500_CACHE)
        return symbols
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch S&P 500 list: %s", exc)
        if _SP500_CACHE.exists():
            df = pd.read_csv(_SP500_CACHE)
            return df["symbol"].str.upper().tolist()
        return []


def fetch_sp400_symbols(force_refresh: bool = False) -> list[str]:
    """Return S&P MidCap 400 ticker symbols, fetching from Wikipedia once and caching."""
    return _fetch_wiki_symbols(_SP400_WIKI_URL, _SP400_CACHE, "S&P 400", force_refresh)


def fetch_sp600_symbols(force_refresh: bool = False) -> list[str]:
    """Return S&P SmallCap 600 ticker symbols, fetching from Wikipedia once and caching."""
    return _fetch_wiki_symbols(_SP600_WIKI_URL, _SP600_CACHE, "S&P 600", force_refresh)


def fetch_nasdaq100_symbols(force_refresh: bool = False) -> list[str]:
    """Return NASDAQ-100 ticker symbols, fetching from Wikipedia once and caching."""
    return _fetch_wiki_symbols(_NASDAQ100_WIKI_URL, _NASDAQ100_CACHE, "NASDAQ-100", force_refresh)


def fetch_sp1000_symbols(force_refresh: bool = False) -> list[str]:
    """Return S&P 1000 = MidCap 400 ∪ SmallCap 600, de-duplicated and sorted."""
    sp400 = fetch_sp400_symbols(force_refresh)
    sp600 = fetch_sp600_symbols(force_refresh)
    combined = sorted(set(sp400) | set(sp600))
    logger.info("S&P 1000: %d from SP400 + %d from SP600 = %d unique", len(sp400), len(sp600), len(combined))
    return combined


class Universe:
    """Manages the set of symbols the system operates on.

    Parameters
    ----------
    watchlist_path:
        Path to the user's watchlist CSV (symbol,exchange).  Used when
        reading watchlist symbols directly from CSV (legacy / seed path).
    include_sp500:
        When True the S&P 500 list is merged in.
    include_sp1000:
        When True the S&P 1000 (400+600) list is merged in.
    extra_symbols:
        Additional symbols to include (e.g. from the watchlist DB).
    """

    def __init__(
        self,
        watchlist_path: Path | str | None = None,
        include_sp500: bool = True,
        include_sp1000: bool = False,
        extra_symbols: list[str] | None = None,
    ) -> None:
        _ensure_data_dir()

        if watchlist_path is None:
            watchlist_path = _DATA_DIR / "watchlist.csv"

        self._watchlist_path = Path(watchlist_path)
        self._include_sp500 = include_sp500
        self._include_sp1000 = include_sp1000
        self._extra_symbols: list[str] = list(extra_symbols or [])
        self._symbols: list[str] | None = None

    def _load(self) -> list[str]:
        symbols: set[str] = set()

        # 1. User watchlist from CSV.
        if self._watchlist_path.exists():
            try:
                df = pd.read_csv(self._watchlist_path)
                if "symbol" not in df.columns:
                    logger.warning(
                        "watchlist.csv has no 'symbol' column — skipping. "
                        "Expected header: symbol,exchange"
                    )
                else:
                    wl = df["symbol"].str.upper().dropna().tolist()
                    symbols.update(wl)
                    logger.info("Loaded %d symbols from watchlist %s", len(wl), self._watchlist_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read watchlist %s: %s", self._watchlist_path, exc)
        else:
            logger.debug("No watchlist found at %s", self._watchlist_path)

        # 2. Extra symbols (e.g. from watchlist DB).
        if self._extra_symbols:
            symbols.update(s.upper() for s in self._extra_symbols)

        # 3. S&P 500.
        if self._include_sp500:
            sp500 = fetch_sp500_symbols()
            symbols.update(sp500)

        # 4. S&P 1000 (MidCap 400 + SmallCap 600).
        if self._include_sp1000:
            sp1000 = fetch_sp1000_symbols()
            symbols.update(sp1000)

        result = sorted(symbols)
        logger.info("Universe contains %d symbols total", len(result))
        return result

    @property
    def symbols(self) -> list[str]:
        """Full sorted list of symbols in the universe."""
        if self._symbols is None:
            self._symbols = self._load()
        return self._symbols

    def reload(self) -> list[str]:
        """Force a reload (e.g. after editing watchlist.csv)."""
        self._symbols = None
        return self.symbols

    def watchlist_symbols(self) -> list[str]:
        """Return only symbols from the user's watchlist CSV (not the full S&P lists)."""
        if not self._watchlist_path.exists():
            return []
        try:
            df = pd.read_csv(self._watchlist_path)
            return df["symbol"].str.upper().dropna().tolist()
        except Exception:  # noqa: BLE001
            return []

    def create_example_watchlist(self) -> None:
        """Write a sample watchlist.csv if none exists yet."""
        if self._watchlist_path.exists():
            logger.info("Watchlist already exists at %s", self._watchlist_path)
            return
        self._watchlist_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            [
                {"symbol": "AAPL", "exchange": "NASDAQ"},
                {"symbol": "MSFT", "exchange": "NASDAQ"},
                {"symbol": "NVDA", "exchange": "NASDAQ"},
            ]
        )
        df.to_csv(self._watchlist_path, index=False)
        logger.info("Created example watchlist at %s", self._watchlist_path)

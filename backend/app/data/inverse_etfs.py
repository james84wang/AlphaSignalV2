"""Loader for the user-editable inverse-ETF mapping at data/inverse_etfs.csv.

CSV columns: underlying_symbol, inverse_etf_symbol, leverage, note

The map is read fresh from disk on every call (small file; no caching needed).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]   # AlphaSignalV2/
_INVERSE_ETFS_PATH = _REPO_ROOT / "data" / "inverse_etfs.csv"

_REQUIRED_COLS = {"underlying_symbol", "inverse_etf_symbol", "leverage", "note"}


def load_inverse_etf_map(path: Path | None = None) -> dict[str, dict]:
    """Return {underlying_symbol -> {inverse_etf_symbol, leverage, note}}.

    Returns an empty dict if the file doesn't exist or is malformed.
    """
    csv_path = path or _INVERSE_ETFS_PATH
    if not csv_path.exists():
        logger.warning("inverse_etfs.csv not found at %s — no mappings loaded", csv_path)
        return {}

    try:
        df = pd.read_csv(csv_path)
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            logger.error("inverse_etfs.csv is missing columns: %s", missing)
            return {}

        result: dict[str, dict] = {}
        for _, row in df.iterrows():
            underlying = str(row["underlying_symbol"]).strip().upper()
            if not underlying:
                continue
            result[underlying] = {
                "inverse_etf_symbol": str(row["inverse_etf_symbol"]).strip().upper(),
                "leverage": int(row["leverage"]),
                "note": str(row["note"]).strip() if pd.notna(row["note"]) else "",
            }
        logger.debug("Loaded %d inverse-ETF mappings from %s", len(result), csv_path)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load inverse_etfs.csv: %s", exc)
        return {}


def get_inverse_etf(symbol: str, path: Path | None = None) -> str | None:
    """Return the inverse ETF symbol for *symbol*, or None if no mapping exists."""
    mapping = load_inverse_etf_map(path)
    entry = mapping.get(symbol.upper())
    return entry["inverse_etf_symbol"] if entry else None

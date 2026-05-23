"""Shared fixtures for data-layer tests.  No real network calls."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest


def make_bars(
    symbol: str = "AAPL",
    start: date = date(2024, 1, 2),
    n: int = 5,
) -> pd.DataFrame:
    """Return a minimal synthetic OHLCV DataFrame."""
    idx = pd.date_range(start=str(start), periods=n, freq="B")  # business days
    rng = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n).astype("int64"),
        },
        index=idx,
    )

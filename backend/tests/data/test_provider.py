"""Tests for provider.py — validate_bars and ProviderError."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.app.data.provider import ProviderError, validate_bars
from backend.tests.data.conftest import make_bars


def test_validate_bars_passes_valid_data():
    df = make_bars(n=10)
    result = validate_bars(df, "AAPL")
    assert len(result) == 10


def test_validate_bars_empty_is_ok():
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = validate_bars(df, "AAPL")
    assert result.empty


def test_validate_bars_raises_on_missing_columns():
    df = make_bars(n=5).drop(columns=["volume"])
    with pytest.raises(ProviderError, match="Missing columns"):
        validate_bars(df, "AAPL")


def test_validate_bars_raises_on_nan_in_ohlc():
    df = make_bars(n=5).copy()
    df.loc[df.index[2], "close"] = np.nan
    with pytest.raises(ProviderError, match="NaN values"):
        validate_bars(df, "AAPL")


def test_validate_bars_raises_on_zero_volume():
    df = make_bars(n=5).copy()
    df.loc[df.index[0], "volume"] = 0
    with pytest.raises(ProviderError, match="Non-positive volume"):
        validate_bars(df, "AAPL")


def test_validate_bars_raises_on_negative_volume():
    df = make_bars(n=5).copy()
    df.loc[df.index[1], "volume"] = -100
    with pytest.raises(ProviderError, match="Non-positive volume"):
        validate_bars(df, "AAPL")


def test_validate_bars_raises_on_non_monotonic_index():
    df = make_bars(n=5).copy()
    # Reverse the index so it's decreasing.
    df = df.iloc[::-1]
    with pytest.raises(ProviderError, match="monotonically increasing"):
        validate_bars(df, "AAPL")

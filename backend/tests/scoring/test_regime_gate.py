"""Regime-gate tests: EMA-fast > EMA-slow, both rising, close > EMA-slow."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.scoring.confluence import compute_events


@pytest.fixture(scope="module")
def strat():
    return load_config().get_strategy("hidden_div")


def _df(close: np.ndarray) -> pd.DataFrame:
    n = len(close)
    idx = pd.bdate_range("2020-01-02", periods=n)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": np.full(n, 1e6)},
        index=idx,
    )


def test_gate_true_in_steady_uptrend(strat):
    # Monotonic uptrend → EMA50 > EMA200, both rising, price above EMA200.
    close = np.linspace(50.0, 200.0, 320)
    ev = compute_events(_df(close), strat)
    assert ev.regime_gate[-1]  # gate open at the end of a clean uptrend


def test_gate_false_in_downtrend(strat):
    # Monotonic downtrend → EMA50 < EMA200 and falling → gate closed.
    close = np.linspace(200.0, 50.0, 320)
    ev = compute_events(_df(close), strat)
    assert not ev.regime_gate[-1]
    assert ev.regime_gate.sum() == 0


def test_gate_false_when_price_below_slow_ema(strat):
    # Long uptrend, then a sharp drop so close < EMA200 even though EMAs stay ordered.
    up = np.linspace(50.0, 200.0, 300)
    drop = np.full(15, 90.0)  # well below the EMA200 level built up by the trend
    ev = compute_events(_df(np.concatenate([up, drop])), strat)
    assert not ev.regime_gate[-1]  # close < EMA200 closes the gate


def test_gate_requires_both_emas_rising(strat):
    # A trend that has rolled over (recent bars flat/declining) → slope test fails.
    up = np.linspace(50.0, 200.0, 260)
    flat = np.linspace(200.0, 170.0, 60)  # EMA50 starts turning down
    ev = compute_events(_df(np.concatenate([up, flat])), strat)
    assert not ev.regime_gate[-1]

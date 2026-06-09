"""Tests for hidden-bullish / regular-bearish divergence detection."""
from __future__ import annotations

import numpy as np

from backend.app.indicators.divergence import detect_divergences
from backend.app.indicators.swing_pivots import Pivot


def test_hidden_bullish_detected_on_confirm_bar():
    n = 30
    # Two pivot lows: price higher-low (8 → 10), oscillator lower-low (40 → 30).
    lows = [Pivot(idx=5, value=8.0, confirm=10), Pivot(idx=15, value=10.0, confirm=20)]
    osc = np.zeros(n)
    osc[5] = 40.0
    osc[15] = 30.0
    hidden_bull, regular_bear = detect_divergences(osc, lows, [], n, min_bars=5, max_bars=60, right=5)
    assert hidden_bull[20]  # confirm bar of the second pivot
    assert hidden_bull.sum() == 1
    assert regular_bear.sum() == 0


def test_regular_bearish_detected():
    n = 30
    highs = [Pivot(idx=5, value=20.0, confirm=10), Pivot(idx=15, value=22.0, confirm=20)]
    osc = np.zeros(n)
    osc[5] = 70.0
    osc[15] = 60.0  # lower high on oscillator
    hidden_bull, regular_bear = detect_divergences(osc, [], highs, n, min_bars=5, max_bars=60, right=5)
    assert regular_bear[20]
    assert hidden_bull.sum() == 0


def test_no_divergence_when_oscillator_agrees():
    n = 30
    lows = [Pivot(idx=5, value=8.0, confirm=10), Pivot(idx=15, value=10.0, confirm=20)]
    osc = np.zeros(n)
    osc[5] = 30.0
    osc[15] = 40.0  # higher low on oscillator → NOT hidden bullish
    hidden_bull, _ = detect_divergences(osc, lows, [], n, min_bars=5, max_bars=60, right=5)
    assert hidden_bull.sum() == 0


def test_gap_outside_min_max_skipped():
    n = 80
    # Gap of 2 bars < min_bars 5 → skipped.
    lows = [Pivot(idx=5, value=8.0, confirm=8), Pivot(idx=7, value=10.0, confirm=10)]
    osc = np.zeros(n)
    osc[5] = 40.0
    osc[7] = 30.0
    hidden_bull, _ = detect_divergences(osc, lows, [], n, min_bars=5, max_bars=60, right=3)
    assert hidden_bull.sum() == 0


def test_regular_bearish_not_flagged_when_price_not_higher_high():
    n = 30
    # Lower high in price → not a regular-bearish setup, even with osc lower-high.
    highs = [Pivot(idx=5, value=22.0, confirm=10), Pivot(idx=15, value=20.0, confirm=20)]
    osc = np.zeros(n)
    osc[5] = 70.0
    osc[15] = 60.0
    _, regular_bear = detect_divergences(osc, [], highs, n, min_bars=5, max_bars=60, right=5)
    assert regular_bear.sum() == 0


def test_regular_bearish_gap_too_large_skipped():
    n = 120
    highs = [Pivot(idx=5, value=20.0, confirm=10), Pivot(idx=100, value=22.0, confirm=105)]
    osc = np.zeros(n)
    osc[5] = 70.0
    osc[100] = 60.0  # gap 95 > max_bars 60 → skipped
    _, regular_bear = detect_divergences(osc, [], highs, n, min_bars=5, max_bars=60, right=5)
    assert regular_bear.sum() == 0


def test_regular_bearish_nan_oscillator_skipped():
    n = 30
    highs = [Pivot(idx=5, value=20.0, confirm=10), Pivot(idx=15, value=22.0, confirm=20)]
    osc = np.full(n, np.nan)  # warm-up region → no comparison possible
    _, regular_bear = detect_divergences(osc, [], highs, n, min_bars=5, max_bars=60, right=5)
    assert regular_bear.sum() == 0

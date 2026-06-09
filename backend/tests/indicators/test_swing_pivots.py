"""Tests for confirmed swing pivot detection (non-repainting)."""
from __future__ import annotations

import numpy as np

from backend.app.indicators.swing_pivots import find_pivots


def test_pivot_low_detected_with_confirmation_lag():
    # Unique trough at index 3; left=right=2 → confirmed at index 5.
    low = np.array([5, 4, 3, 2, 3, 4, 5], dtype=float)
    high = np.array([5, 6, 7, 8, 7, 6, 5], dtype=float)  # unique peak at idx 3 too
    lows, highs = find_pivots(high, low, left=2, right=2)
    assert len(lows) == 1
    assert lows[0].idx == 3
    assert lows[0].value == 2.0
    assert lows[0].confirm == 5  # idx + right
    assert len(highs) == 1
    assert highs[0].idx == 3
    assert highs[0].confirm == 5


def test_tie_is_skipped():
    # Two equal minima → not a unique pivot → skipped.
    low = np.array([5, 2, 3, 2, 4, 5, 6], dtype=float)
    high = np.array([1, 2, 3, 4, 5, 6, 7], dtype=float)
    lows, _ = find_pivots(high, low, left=2, right=2)
    assert lows == []


def test_no_pivot_when_insufficient_bars():
    low = np.array([3, 2, 1], dtype=float)
    high = np.array([1, 2, 3], dtype=float)
    lows, highs = find_pivots(high, low, left=2, right=2)
    assert lows == [] and highs == []


def test_multiple_pivots_ordered():
    low = np.array([5, 3, 5, 5, 2, 5, 5, 1, 5], dtype=float)
    high = np.array([1, 2, 1, 1, 2, 1, 1, 2, 1], dtype=float)
    lows, _ = find_pivots(high, low, left=1, right=1)
    idxs = [p.idx for p in lows]
    assert idxs == sorted(idxs)
    assert 1 in idxs and 4 in idxs and 7 in idxs


def test_non_repaint_pivot_only_known_after_right_bars():
    """Parity invariant: a swing low at bar k is NOT detectable until bar k+right.

    This is the confirmation lag that keeps the Python port non-repainting and in
    sync with the .pine (the signal sits at low + lbR, never at the low itself).
    """
    left = right = 2
    k = 3  # the trough
    low = np.array([5, 4, 3, 2, 3, 4, 5], dtype=float)
    high = np.array([5, 6, 7, 8, 7, 6, 5], dtype=float)

    # Truncated one bar before confirmation (k+right-1) → pivot NOT yet known.
    cut = k + right  # number of bars = indices 0..k+right-1
    lows_early, _ = find_pivots(high[:cut], low[:cut], left, right)
    assert all(p.idx != k for p in lows_early), "pivot detected before its right bars printed (repaint!)"

    # Exactly at confirmation (k+right+1 bars) → pivot now known, confirm == k+right.
    lows_conf, _ = find_pivots(high[: k + right + 1], low[: k + right + 1], left, right)
    assert any(p.idx == k and p.confirm == k + right for p in lows_conf)

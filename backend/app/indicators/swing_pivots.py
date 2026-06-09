"""Confirmed swing pivot detection.

Implements the non-repainting pivot rule from
``V2-1/hidden_div_confluence_logic.md`` §7 and §10:

A swing low (high) at bar *p* is the strict minimum (maximum) over the window
``[p-left, p+right]``.  Because ``right`` bars to the *right* are required, the
pivot is only **known** at bar ``p + right`` — never earlier.  All downstream
divergence logic must respect this confirmation lag, or the backtest will not
match live behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Pivot:
    """A single confirmed swing pivot.

    Attributes
    ----------
    idx:      bar position where the pivot price printed.
    value:    the low (for a pivot low) or high (for a pivot high) at ``idx``.
    confirm:  bar position at which the pivot becomes known (= ``idx + right``).
    """

    idx: int
    value: float
    confirm: int


def find_pivots(
    high: np.ndarray,
    low: np.ndarray,
    left: int,
    right: int,
) -> tuple[list[Pivot], list[Pivot]]:
    """Return ``(pivot_lows, pivot_highs)`` as lists of :class:`Pivot`, oldest first.

    A pivot must be the *unique* extreme in its window (ties are skipped) so that
    detection is deterministic.  No look-ahead: a pivot at ``idx`` is reported
    with ``confirm = idx + right``; callers must not act on it before that bar.
    """
    n = len(low)
    lows: list[Pivot] = []
    highs: list[Pivot] = []
    if n == 0 or left < 1 or right < 1:
        return lows, highs

    for p in range(left, n - right):
        win_lo = low[p - left : p + right + 1]
        lo_val = low[p]
        if lo_val == win_lo.min() and np.count_nonzero(win_lo == lo_val) == 1:
            lows.append(Pivot(idx=p, value=float(lo_val), confirm=p + right))

        win_hi = high[p - left : p + right + 1]
        hi_val = high[p]
        if hi_val == win_hi.max() and np.count_nonzero(win_hi == hi_val) == 1:
            highs.append(Pivot(idx=p, value=float(hi_val), confirm=p + right))

    return lows, highs

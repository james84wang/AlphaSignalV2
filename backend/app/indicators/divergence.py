"""Hidden-bullish and regular-bearish divergence detection.

Implements ``V2-1/hidden_div_confluence_logic.md`` §2, §4, §7.

| Pattern            | Price (pivots)  | Oscillator      | Used for |
|--------------------|-----------------|-----------------|----------|
| Hidden bullish     | higher **low**  | lower **low**   | Entries  |
| Regular bearish    | higher **high** | lower **high**  | Exits    |

The oscillator is the **MACD line** or the **RSI** (the caller chooses).  A
divergence between two *consecutive* confirmed pivots is flagged on the
confirmation bar of the *second* pivot (``idx2 + right``) — never earlier — so
the signal is non-repainting but lagged, exactly as the spec requires.

Only pivot pairs whose spacing is within ``[min_bars, max_bars]`` are
considered (a pullback that is too short is noise; one that is too long is a
different swing).
"""
from __future__ import annotations

import numpy as np

from backend.app.indicators.swing_pivots import Pivot


def _osc_at(osc: np.ndarray, idx: int) -> float | None:
    """Oscillator value at a pivot bar, or ``None`` when it is NaN/out of range."""
    if idx < 0 or idx >= len(osc):
        return None
    val = osc[idx]
    if val is None or np.isnan(val):
        return None
    return float(val)


def detect_divergences(
    osc: np.ndarray,
    pivot_lows: list[Pivot],
    pivot_highs: list[Pivot],
    n_bars: int,
    *,
    min_bars: int,
    max_bars: int,
    right: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(hidden_bull, regular_bear)`` boolean arrays of length ``n_bars``.

    ``hidden_bull[b]``  is True when a hidden-bullish divergence is confirmed on bar ``b``.
    ``regular_bear[b]`` is True when a regular-bearish divergence is confirmed on bar ``b``.
    """
    hidden_bull = np.zeros(n_bars, dtype=bool)
    regular_bear = np.zeros(n_bars, dtype=bool)

    # Hidden bullish: consecutive pivot lows, price higher-low, oscillator lower-low.
    for prev, cur in zip(pivot_lows, pivot_lows[1:]):
        gap = cur.idx - prev.idx
        if gap < min_bars or gap > max_bars:
            continue
        o_prev = _osc_at(osc, prev.idx)
        o_cur = _osc_at(osc, cur.idx)
        if o_prev is None or o_cur is None:
            continue
        if cur.value > prev.value and o_cur < o_prev:
            confirm = cur.idx + right
            if 0 <= confirm < n_bars:
                hidden_bull[confirm] = True

    # Regular bearish: consecutive pivot highs, price higher-high, oscillator lower-high.
    for prev, cur in zip(pivot_highs, pivot_highs[1:]):
        gap = cur.idx - prev.idx
        if gap < min_bars or gap > max_bars:
            continue
        o_prev = _osc_at(osc, prev.idx)
        o_cur = _osc_at(osc, cur.idx)
        if o_prev is None or o_cur is None:
            continue
        if cur.value > prev.value and o_cur < o_prev:
            confirm = cur.idx + right
            if 0 <= confirm < n_bars:
                regular_bear[confirm] = True

    return hidden_bull, regular_bear

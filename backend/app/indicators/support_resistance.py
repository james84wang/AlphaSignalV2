"""Support and resistance level identification. Implements spec §4.6.

Algorithm (per spec default):
  1. Identify swing highs/lows using a 5-bar symmetric window (2-bar confirmation lag).
  2. For bar T, only swing points confirmed at T-2 or earlier are used (no look-ahead).
  3. Cluster adjacent levels within cluster_pct of each other.
  4. Nearest unbroken cluster below price = support; above = resistance.

Ambiguity resolutions:
  - Swing high at bar i: h[i] > h[i-2], h[i-1], h[i+1], h[i+2] (strict greater-than).
  - "Unbroken" is simplified to: most recent unclustered level nearest the current price.
  - Lookback capped at 252 bars (~1 year of daily data).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cluster_levels(levels: list[float], cluster_pct: float) -> list[float]:
    """Group sorted levels within cluster_pct of each other; return cluster midpoints."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters: list[float] = []
    current: list[float] = [levels[0]]
    for lvl in levels[1:]:
        if lvl <= current[0] * (1.0 + cluster_pct):
            current.append(lvl)
        else:
            clusters.append(float(np.mean(current)))
            current = [lvl]
    clusters.append(float(np.mean(current)))
    return clusters


def compute_sr_levels(
    df: pd.DataFrame,
    cluster_pct: float = 0.01,
    lookback: int = 252,
) -> pd.DataFrame:
    """Return DataFrame with columns 'support_level' and 'resistance_level' (float, NaN if none found).

    No look-ahead: swing points used for bar T were confirmed at T-2 or earlier.
    """
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    n = len(df)

    support_arr = np.full(n, np.nan)
    resistance_arr = np.full(n, np.nan)

    for t in range(n):
        close_t = closes[t]
        lb_start = max(2, t - lookback)  # need at least 2 bars before i
        lb_end = t - 2  # confirmed at bar i+2 ≤ t means i ≤ t-2

        raw_supports: list[float] = []
        raw_resistances: list[float] = []

        for i in range(lb_start, lb_end + 1):
            # Swing low: strict minimum in 5-bar symmetric window
            if (lows[i] < lows[i - 1] and lows[i] < lows[i - 2]
                    and i + 2 < n
                    and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]):
                raw_supports.append(lows[i])

            # Swing high: strict maximum in 5-bar symmetric window
            if (highs[i] > highs[i - 1] and highs[i] > highs[i - 2]
                    and i + 2 < n
                    and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]):
                raw_resistances.append(highs[i])

        # Filter to levels on the correct side of price, then cluster
        sup_candidates = _cluster_levels(
            [s for s in raw_supports if s < close_t], cluster_pct
        )
        res_candidates = _cluster_levels(
            [r for r in raw_resistances if r > close_t], cluster_pct
        )

        if sup_candidates:
            support_arr[t] = max(sup_candidates)      # nearest support below price
        if res_candidates:
            resistance_arr[t] = min(res_candidates)   # nearest resistance above price

    return pd.DataFrame(
        {"support_level": support_arr, "resistance_level": resistance_arr},
        index=df.index,
    )

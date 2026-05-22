"""P3 and P5 swing pattern detection. Implements spec §4.2 and §4.3.

Ambiguity resolutions:
  - "Lower wicks indicate buying" uses lower_wick / range ≥ 0.25 as the threshold.
  - "Upper wicks indicate selling" uses upper_wick / range ≥ 0.25.
  - P5 "HH+HL" requires ≥ 3 of 4 consecutive bar-pairs to show higher high AND higher low.
  - P5 "major reversal" requires current bar to have the highest (or lowest) close in the
    5-bar window, with an identifiable trough (or peak) in the interior bars (T-3, T-2, T-1).
  - Priority order matches score magnitude (highest absolute score checked first per side).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── P3 ─────────────────────────────────────────────────────────────────────────

def detect_p3_pattern(df: pd.DataFrame, buying_tail_pct: float = 0.25) -> pd.Series:
    """Classify the rolling 3-bar pattern for each bar (including current bar as T).

    No look-ahead: bar T only references T, T-1, T-2.
    Returns a Series of pattern name strings matching config.yaml p3.scores keys.
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).replace(0.0, np.nan)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_tail_pct = (lower_wick / rng).fillna(0.0)
    upper_tail_pct = (upper_wick / rng).fillna(0.0)

    patterns = pd.Series("no_pattern", index=df.index)

    for t in range(2, len(df)):
        b0_c, b1_c, b2_c = c.iat[t - 2], c.iat[t - 1], c.iat[t]
        b0_h, b1_h = h.iat[t - 2], h.iat[t - 1]
        b0_l, b1_l = l.iat[t - 2], l.iat[t - 1]
        lt0, lt1 = lower_tail_pct.iat[t - 2], lower_tail_pct.iat[t - 1]
        ut0, ut1 = upper_tail_pct.iat[t - 2], upper_tail_pct.iat[t - 1]

        # --- Bullish side ---
        # Bullish reversal: current closes highest, prior bars had buying tails
        if (b2_c > b0_c and b2_c > b1_c
                and (lt0 >= buying_tail_pct or lt1 >= buying_tail_pct)
                and min(b0_l, b1_l) <= max(b0_l, b1_l)):
            patterns.iat[t] = "bullish_reversal_at_support"
            continue

        # Bullish breakout: current close above both prior highs
        if b2_c > max(b0_h, b1_h):
            patterns.iat[t] = "bullish_breakout_above_resistance"
            continue

        # --- Bearish side ---
        # Bearish reversal: current closes lowest, prior bars had selling tails
        if (b2_c < b0_c and b2_c < b1_c
                and (ut0 >= buying_tail_pct or ut1 >= buying_tail_pct)
                and max(b0_h, b1_h) >= min(b0_h, b1_h)):
            patterns.iat[t] = "bearish_reversal_at_resistance"
            continue

        # Bearish breakdown: current close below both prior lows
        if b2_c < min(b0_l, b1_l):
            patterns.iat[t] = "bearish_breakdown_below_support"
            continue

        # Continuation up: monotone increasing closes
        if b2_c > b1_c > b0_c:
            patterns.iat[t] = "continuation_up"
            continue

        # Continuation down: monotone decreasing closes
        if b2_c < b1_c < b0_c:
            patterns.iat[t] = "continuation_down"

    return patterns


# ── P5 ─────────────────────────────────────────────────────────────────────────

def detect_p5_pattern(df: pd.DataFrame, hh_hl_min_pairs: int = 3) -> pd.Series:
    """Classify the rolling 5-bar pattern for each bar (including current bar as T).

    No look-ahead: bar T only references T, T-1, T-2, T-3, T-4.
    Returns a Series of pattern name strings matching config.yaml p5.scores keys.
    """
    h, l, c = df["high"], df["low"], df["close"]
    patterns = pd.Series("no_pattern", index=df.index)

    for t in range(4, len(df)):
        closes = [c.iat[t - 4], c.iat[t - 3], c.iat[t - 2], c.iat[t - 1], c.iat[t]]
        highs  = [h.iat[t - 4], h.iat[t - 3], h.iat[t - 2], h.iat[t - 1], h.iat[t]]
        lows   = [l.iat[t - 4], l.iat[t - 3], l.iat[t - 2], l.iat[t - 1], l.iat[t]]

        curr_close = closes[4]
        interior_closes = closes[1:4]  # T-3, T-2, T-1

        # --- Major bullish reversal ---
        # Current bar has highest close; interior bars have at least one trough below endpoints
        if curr_close == max(closes) and min(interior_closes) < min(closes[0], curr_close):
            patterns.iat[t] = "major_bullish_reversal"
            continue

        # --- Major bearish reversal ---
        if curr_close == min(closes) and max(interior_closes) > max(closes[0], curr_close):
            patterns.iat[t] = "major_bearish_reversal"
            continue

        # --- Bullish trend confirmation: HH+HL across ≥ hh_hl_min_pairs consecutive pairs ---
        hh_count = sum(highs[i + 1] > highs[i] for i in range(4))
        hl_count = sum(lows[i + 1] > lows[i] for i in range(4))
        if hh_count >= hh_hl_min_pairs and hl_count >= hh_hl_min_pairs:
            patterns.iat[t] = "bullish_trend_confirmation"
            continue

        # --- Bearish trend confirmation: LH+LL ---
        lh_count = sum(highs[i + 1] < highs[i] for i in range(4))
        ll_count = sum(lows[i + 1] < lows[i] for i in range(4))
        if lh_count >= hh_hl_min_pairs and ll_count >= hh_hl_min_pairs:
            patterns.iat[t] = "bearish_trend_confirmation"
            continue

        patterns.iat[t] = "range_bound"

    return patterns

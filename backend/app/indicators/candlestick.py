"""Candlestick pattern detection. Implements spec §4.1.

Pattern priority (most to least specific):
  1. Long Bullish / Long Bearish Candle  (body ≥ 70% of range)
  2. Green Hammer / Red Hammer (Hanging Man)
  3. Inverted Green Hammer / Inverted Red Hammer (Shooting Star)
  4. Bullish / Bearish Spinning Top
  5. Bullish Doji / Bearish Doji  (by context: at recent low/high)
  6. No clear pattern

Ambiguity resolutions:
  - "Body in upper/lower 1/3" uses the body MIDPOINT position in the full high-low range.
  - "At recent low/high" for doji: close within 3% of the rolling 10-bar low/high.
  - When body = 0 (exact doji), only doji patterns fire (wick-mult conditions need body > 0).
  - Flat bars (high = low) are assigned "no_pattern" via NaN propagation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_candlestick_pattern(
    df: pd.DataFrame,
    long_candle_body_pct: float = 0.70,
    hammer_wick_mult: float = 2.0,
    doji_body_pct: float = 0.05,
    doji_lookback: int = 10,
) -> pd.Series:
    """Return a Series of pattern name strings, one per bar.

    No look-ahead: doji context uses only bars ≤ T (rolling backward window).
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]

    rng = (h - l).replace(0.0, np.nan)  # flat bars → NaN → no pattern
    body = (c - o).abs()
    body_pct = body / rng
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    body_mid_pct = ((o + c) / 2 - l) / rng  # 0 = bottom of range, 1 = top

    is_green = c > o
    is_red = c < o
    is_doji = body_pct <= doji_body_pct  # also catches body=0 (NaN body_pct → False)

    # Doji context (rolling lookback, no look-ahead)
    rolling_low = c.rolling(doji_lookback, min_periods=1).min()
    rolling_high = c.rolling(doji_lookback, min_periods=1).max()
    at_recent_low = c <= rolling_low * 1.03
    at_recent_high = c >= rolling_high * 0.97

    # Spinning top: small body that isn't dominant and sits in the middle third
    is_small_body = (body_pct < 0.30) & (~is_doji)

    patterns = pd.Series("no_pattern", index=df.index)
    remaining = pd.Series(True, index=df.index)

    def assign(mask: pd.Series, name: str) -> None:
        nonlocal remaining
        m = remaining & mask.fillna(False)
        patterns[m] = name
        remaining[m] = False

    # 1. Long candles
    assign(is_green & (body_pct >= long_candle_body_pct), "long_bullish_candle")
    assign(is_red & (body_pct >= long_candle_body_pct), "long_bearish_candle")

    # 2. Hammers: body near top of range, long lower wick, minimal upper wick
    assign(
        is_green & (~is_doji)
        & (body_mid_pct >= 2 / 3)
        & (lower_wick >= hammer_wick_mult * body)
        & (upper_wick <= body),
        "green_hammer",
    )
    assign(
        is_red & (~is_doji)
        & (body_mid_pct >= 2 / 3)
        & (lower_wick >= hammer_wick_mult * body)
        & (upper_wick <= body),
        "red_hammer",
    )

    # 3. Inverted hammers: body near bottom of range, long upper wick, minimal lower wick
    assign(
        is_green & (~is_doji)
        & (body_mid_pct <= 1 / 3)
        & (upper_wick >= hammer_wick_mult * body)
        & (lower_wick <= body),
        "inverted_green_hammer",
    )
    assign(
        is_red & (~is_doji)
        & (body_mid_pct <= 1 / 3)
        & (upper_wick >= hammer_wick_mult * body)
        & (lower_wick <= body),
        "inverted_red_hammer",
    )

    # 4. Spinning tops: small body in middle third, wicks on both sides
    assign(
        is_green & is_small_body
        & (lower_wick > body) & (upper_wick > body)
        & (body_mid_pct > 1 / 3) & (body_mid_pct < 2 / 3),
        "bullish_spinning_top",
    )
    assign(
        is_red & is_small_body
        & (lower_wick > body) & (upper_wick > body)
        & (body_mid_pct > 1 / 3) & (body_mid_pct < 2 / 3),
        "bearish_spinning_top",
    )

    # 5. Dojis: body within 5% of range, context-dependent
    assign(is_doji & at_recent_low, "bullish_doji")
    assign(is_doji & at_recent_high, "bearish_doji")

    return patterns

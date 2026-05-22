"""Support/Resistance sub-score. Implements spec §4.6."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.config import SrConfig


def score_sr(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    sr_df: pd.DataFrame,
    cfg: SrConfig,
) -> pd.Series:
    """Return S/R sub-score Series in [-100, +100].

    Uses a 20-bar rolling average for 'avg range' and 30-bar for avg volume.
    No look-ahead: all rolling windows look backward only.
    """
    support = sr_df["support_level"]
    resistance = sr_df["resistance_level"]
    avg_vol = volume.rolling(30, min_periods=1).mean()
    avg_range = (high - low).rolling(20, min_periods=1).mean()
    bar_range = high - low
    midpoint = (high + low) / 2

    sc = cfg.scores
    result = pd.Series(sc.no_interaction, index=close.index)

    # Breakout above resistance: close above resistance with volume ≥ 1.5× avg
    breakout = (
        resistance.notna()
        & (close > resistance)
        & (volume >= avg_vol * cfg.breakout_volume_mult)
    )
    result[breakout] = sc.breakout_above_resistance

    # Breakdown below support: close below support with volume ≥ 1.5× avg
    breakdown = (
        support.notna()
        & (close < support)
        & (volume >= avg_vol * cfg.breakout_volume_mult)
    )
    result[breakdown] = sc.breakdown_below_support

    # Strong bounce off support: low ≤ support, close ≥ midpoint, range > avg_range
    bounce = (
        support.notna()
        & (low <= support)
        & (close >= midpoint)
        & (bar_range > avg_range)
        & ~breakdown
    )
    result[bounce] = sc.strong_bounce_off_support

    # Strong rejection off resistance: high ≥ resistance, close ≤ midpoint, range > avg_range
    rejection = (
        resistance.notna()
        & (high >= resistance)
        & (close <= midpoint)
        & (bar_range > avg_range)
        & ~breakout
    )
    result[rejection] = sc.strong_rejection_off_resistance

    # Approach support (touched, no strong bounce)
    approach_sup = (
        support.notna()
        & (low <= support)
        & ~bounce
        & ~breakdown
    )
    result[approach_sup] = sc.approach_support

    # Approach resistance (touched, no strong rejection)
    approach_res = (
        resistance.notna()
        & (high >= resistance)
        & ~rejection
        & ~breakout
    )
    result[approach_res] = sc.approach_resistance

    return result.rename("sr_score")

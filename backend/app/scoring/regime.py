"""Regime filter — EMA200 gate. Implements spec §3."""
from __future__ import annotations

import pandas as pd

from backend.app.config import RegimeConfig


def compute_regime(
    close: pd.Series,
    ema_df: pd.DataFrame,
    cfg: RegimeConfig,
) -> pd.DataFrame:
    """Return DataFrame with boolean columns 'long_allowed' and 'short_allowed'.

    Rule (spec §3):
      Price > EMA200 AND slope ≥ 0 → long only
      Price < EMA200 AND slope ≤ 0 → short only
      Mixed / flat                  → both allowed
    No look-ahead: all inputs are backward-looking.
    """
    ema200 = ema_df["ema_200"]
    slope = ema_df["ema200_slope"]  # +1, 0, or -1

    price_above = close > ema200
    price_below = close < ema200
    slope_up = slope >= 0
    slope_down = slope <= 0

    bull_regime = price_above & slope_up
    bear_regime = price_below & slope_down

    long_allowed = ~bear_regime   # True except in pure bear regime
    short_allowed = ~bull_regime  # True except in pure bull regime

    return pd.DataFrame(
        {"long_allowed": long_allowed, "short_allowed": short_allowed},
        index=close.index,
    )

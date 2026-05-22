"""Volume sub-score (contextual). Implements spec §4.4.

Design: volume is scored as an amplifier on price direction.
  - Bullish candle → positive score for high RV, negative for low RV.
  - Bearish candle → signs are inverted.
  - Doji or spinning top → sub-score = 0 regardless of RV.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.config import VolumeConfig

_NEUTRAL_PATTERNS = frozenset({
    "bullish_doji", "bearish_doji",
    "bullish_spinning_top", "bearish_spinning_top",
})


def score_volume(
    close: pd.Series,
    open_: pd.Series,
    volume: pd.Series,
    pattern_series: pd.Series,
    cfg: VolumeConfig,
) -> pd.Series:
    """Return volume sub-score Series.

    Uses a 30-bar inclusive rolling average as the RV baseline.
    RV = current volume / avg_volume.
    No look-ahead: rolling average only uses bars ≤ T.
    """
    avg_vol = volume.rolling(cfg.avg_period, min_periods=1).mean()
    rv = volume / avg_vol.replace(0, np.nan)

    is_bullish = close > open_
    is_bearish = close < open_
    is_neutral = pattern_series.isin(_NEUTRAL_PATTERNS)

    # Build lookup table from config buckets (bullish side)
    def _lookup_rv(rv_val: float) -> float:
        if pd.isna(rv_val):
            return 0.0
        for bucket in cfg.bullish_buckets:
            lo = bucket.rv_min if bucket.rv_min is not None else -np.inf
            hi = bucket.rv_max if bucket.rv_max is not None else np.inf
            if lo <= rv_val < hi:
                return bucket.score
        return 0.0

    base_score = rv.map(_lookup_rv)

    result = pd.Series(0.0, index=close.index)
    result[is_neutral] = 0.0
    result[is_bullish & ~is_neutral] = base_score[is_bullish & ~is_neutral]
    result[is_bearish & ~is_neutral] = -base_score[is_bearish & ~is_neutral]

    return result.rename("vol_score")

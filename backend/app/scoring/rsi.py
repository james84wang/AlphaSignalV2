"""RSI sub-score. Implements spec §4.8. No divergence (handled in MACD)."""
from __future__ import annotations

import pandas as pd

from backend.app.config import RsiConfig


def score_rsi(rsi: pd.Series, cfg: RsiConfig) -> pd.Series:
    """Return RSI sub-score Series in [-100, +100].

    Precedence: cross events are checked first (they are the strongest triggers).
    'Rising' = rsi[T] > rsi[T-1]; 'falling' = rsi[T] < rsi[T-1].
    No look-ahead: only uses rsi.shift(1).
    """
    sc = cfg.scores
    prev = rsi.shift(1)
    rising  = rsi > prev
    falling = rsi < prev

    result = pd.Series(0.0, index=rsi.index)
    assigned = pd.Series(False, index=rsi.index)

    def assign(mask: pd.Series, value: float) -> None:
        m = ~assigned & mask.fillna(False)
        result[m] = value
        assigned[m] = True

    # Cross events take highest priority
    assign((prev <= 30) & (rsi > 30), sc.crosses_up_30)
    assign((prev >= 70) & (rsi < 70), sc.crosses_down_70)

    # Zone + direction
    assign((rsi < 30) & rising,  sc.below_30_rising)
    assign((rsi < 30) & falling, sc.below_30_falling)
    assign((rsi >= 30) & (rsi < 50) & rising,  sc.between_30_50_rising)
    assign((rsi >= 30) & (rsi < 50) & falling, sc.between_30_50_falling)
    assign((rsi >= 50) & (rsi < 70) & rising,  sc.between_50_70_rising)
    assign((rsi >= 50) & (rsi < 70) & falling, sc.between_50_70_falling)
    assign((rsi >= 70) & rising,  sc.above_70_rising)
    assign((rsi >= 70) & falling, sc.above_70_falling)

    return result.rename("rsi_score")

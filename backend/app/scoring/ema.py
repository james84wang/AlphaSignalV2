"""EMA system sub-score. Implements spec §4.5.

Two sub-signals:
  A. Stacking score (position of price relative to EMA20/50/100/200)
  B. Cross-event score (fires only on the bar a cross occurs)
Final = max(|A|, |B|) preserving sign.
"""
from __future__ import annotations

import pandas as pd

from backend.app.config import EmaConfig


def score_ema(
    close: pd.Series,
    ema_df: pd.DataFrame,
    cfg: EmaConfig,
) -> pd.Series:
    """Return EMA sub-score Series in [-100, +100].

    No look-ahead: cross detection uses close.shift(1) and ema.shift(1).
    """
    ema20 = ema_df["ema_20"]
    ema50 = ema_df["ema_50"]
    ema100 = ema_df["ema_100"]
    ema200 = ema_df["ema_200"]

    # ── A. Stacking score ──────────────────────────────────────────────────────
    full_bull = (close > ema20) & (ema20 > ema50) & (ema50 > ema100) & (ema100 > ema200)
    full_bear = (close < ema20) & (ema20 < ema50) & (ema50 < ema100) & (ema100 < ema200)

    n_above = (
        (close > ema20).astype(int)
        + (close > ema50).astype(int)
        + (close > ema100).astype(int)
        + (close > ema200).astype(int)
    )

    ss = cfg.stacking_scores
    stack_score = pd.Series(0.0, index=close.index)
    stack_score[full_bull] = ss.full_bull
    stack_score[full_bear] = ss.full_bear
    # Only override where neither full condition holds
    neither = ~full_bull & ~full_bear
    stack_score[neither & (n_above >= 3)] = ss.above_3
    stack_score[neither & (n_above == 2)] = ss.above_2
    stack_score[neither & (n_above <= 1)] = ss.below_3

    # ── B. Cross-event score (fires on the cross bar only) ────────────────────
    cs = cfg.cross_scores
    cross_score = pd.Series(0.0, index=close.index)
    prev_close = close.shift(1)

    # Ordered highest absolute score first so the strongest cross wins
    cross_events = [
        (ema200, cs.cross_above_200, cs.cross_below_200),
        (ema100, cs.cross_above_100, cs.cross_below_100),
        (ema50,  cs.cross_above_50,  cs.cross_below_50),
        (ema20,  cs.cross_above_20,  cs.cross_below_20),
    ]
    for ema, above_score, below_score in cross_events:
        prev_ema = ema.shift(1)
        crosses_above = (close > ema) & (prev_close <= prev_ema)
        crosses_below = (close < ema) & (prev_close >= prev_ema)
        # Update only when this cross has larger magnitude than current best
        take_above = crosses_above & (abs(above_score) > cross_score.abs())
        take_below = crosses_below & (abs(below_score) > cross_score.abs())
        cross_score[take_above] = above_score
        cross_score[take_below] = below_score

    # ── Final: max(|stack|, |cross|) preserving sign ──────────────────────────
    use_cross = cross_score.abs() > stack_score.abs()
    final = stack_score.copy()
    final[use_cross] = cross_score[use_cross]

    return final.rename("ema_score")

"""Candlestick sub-score. Implements spec §4.1."""
from __future__ import annotations

import pandas as pd

from backend.app.config import CandlestickConfig


_PATTERN_TO_KEY = {
    "long_bullish_candle": "long_bullish_candle",
    "green_hammer": "green_hammer",
    "inverted_green_hammer": "inverted_green_hammer",
    "bullish_spinning_top": "bullish_spinning_top",
    "bullish_doji": "bullish_doji",
    "bearish_doji": "bearish_doji",
    "bearish_spinning_top": "bearish_spinning_top",
    "inverted_red_hammer": "inverted_red_hammer",
    "red_hammer": "red_hammer",
    "long_bearish_candle": "long_bearish_candle",
    "no_pattern": "no_pattern",
}


def score_candlestick(
    pattern_series: pd.Series,
    at_sr: pd.Series,
    cfg: CandlestickConfig,
) -> pd.Series:
    """Map each bar's candlestick pattern to a sub-score in [-100, +100].

    Applies the §4.1 context multiplier (×1.2, capped at ±100) when the pattern
    occurs at a P5 S/R level (at_sr = True).
    """
    scores_map: dict[str, float] = cfg.scores.model_dump()
    raw = pattern_series.map(lambda p: scores_map.get(p, 0.0))

    mult = cfg.sr_context_multiplier
    adjusted = raw.where(~at_sr, (raw * mult).clip(-100, 100))
    return adjusted.rename("cs_score")

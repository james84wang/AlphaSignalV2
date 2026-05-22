"""MACD sub-score including divergence. Implements spec §4.7.

Sub-score = sum of all triggered micro-signals, clipped to [-100, +100].
Divergence is detected HERE (removed from RSI to avoid double-counting).

Ambiguity resolutions:
  - "Golden cross on current bar" = MACD line crosses ABOVE signal line on bar T.
  - "MACD above zero" = macd_line > 0.
  - "Histogram green expanding" = hist[T] > 0 AND hist[T] > hist[T-1].
  - "Histogram green contracting" = hist[T] > 0 AND hist[T] < hist[T-1] AND hist[T] > 0.
  - "Histogram red expanding" = hist[T] < 0 AND hist[T] < hist[T-1] (more negative).
  - "Histogram red contracting" = hist[T] < 0 AND hist[T] > hist[T-1].
  - Divergence uses up to 50-bar lookback to find two most recent local extrema
    (defined as: bar where close == min/max of prior 5 bars — look-ahead free).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.config import MacdConfig


def _find_local_lows(series: pd.Series, window: int = 5) -> pd.Series:
    """Boolean Series: True at bars that are the rolling window minimum (no look-ahead)."""
    roll_min = series.rolling(window, min_periods=window).min()
    return series == roll_min


def _find_local_highs(series: pd.Series, window: int = 5) -> pd.Series:
    """Boolean Series: True at bars that are the rolling window maximum (no look-ahead)."""
    roll_max = series.rolling(window, min_periods=window).max()
    return series == roll_max


def _detect_divergence(
    close: pd.Series,
    macd_line: pd.Series,
    lookback: int = 50,
) -> tuple[pd.Series, pd.Series]:
    """Return (bullish_div, bearish_div) boolean Series.

    Bullish divergence at bar T: within the last `lookback` bars there exist
    two local price lows where price made a lower low but MACD made a higher low.

    No look-ahead: local extrema detected using backward-only rolling windows.
    """
    close_arr = close.to_numpy(dtype=float)
    macd_arr = macd_line.to_numpy(dtype=float)
    n = len(close)

    price_local_low = _find_local_lows(close).to_numpy()
    price_local_high = _find_local_highs(close).to_numpy()

    bull_div = np.zeros(n, dtype=bool)
    bear_div = np.zeros(n, dtype=bool)

    for t in range(lookback, n):
        lb_start = t - lookback

        # Gather local price lows in lookback window (excluding current bar)
        low_idxs = [i for i in range(lb_start, t) if price_local_low[i]]
        if len(low_idxs) >= 2:
            i1, i2 = low_idxs[-2], low_idxs[-1]  # two most recent lows
            if close_arr[i2] < close_arr[i1] and macd_arr[i2] > macd_arr[i1]:
                bull_div[t] = True

        # Gather local price highs in lookback window
        high_idxs = [i for i in range(lb_start, t) if price_local_high[i]]
        if len(high_idxs) >= 2:
            i1, i2 = high_idxs[-2], high_idxs[-1]
            if close_arr[i2] > close_arr[i1] and macd_arr[i2] < macd_arr[i1]:
                bear_div[t] = True

    return pd.Series(bull_div, index=close.index), pd.Series(bear_div, index=close.index)


def score_macd(
    close: pd.Series,
    macd_df: pd.DataFrame,
    cfg: MacdConfig,
) -> pd.Series:
    """Return MACD sub-score Series: sum of micro-signals clipped to [-100, +100]."""
    ms = cfg.micro_signals
    line = macd_df["macd_line"]
    sig = macd_df["macd_signal"]
    hist = macd_df["macd_hist"]
    prev_hist = hist.shift(1)
    prev_sig = sig.shift(1)
    prev_line = line.shift(1)

    score = pd.Series(0.0, index=close.index)

    # Golden / death cross (MACD crosses signal line)
    golden_cross = (line > sig) & (prev_line <= prev_sig)
    death_cross  = (line < sig) & (prev_line >= prev_sig)
    score[golden_cross] += ms.golden_cross
    score[death_cross]  += ms.death_cross

    # MACD line zero line
    score[line > 0] += ms.macd_above_zero
    score[line < 0] += ms.macd_below_zero

    # Histogram states
    hist_green = hist > 0
    hist_red   = hist < 0
    expanding_green   = hist_green & (hist > prev_hist)
    contracting_green = hist_green & (hist < prev_hist)
    expanding_red     = hist_red   & (hist < prev_hist)   # more negative
    contracting_red   = hist_red   & (hist > prev_hist)   # less negative

    score[expanding_green]   += ms.histogram_green_expanding
    score[contracting_green] += ms.histogram_green_contracting
    score[expanding_red]     += ms.histogram_red_expanding
    score[contracting_red]   += ms.histogram_red_contracting

    # Divergence
    bull_div, bear_div = _detect_divergence(close, line)
    score[bull_div] += ms.bullish_divergence
    score[bear_div] += ms.bearish_divergence

    return score.clip(-100, 100).rename("macd_score")

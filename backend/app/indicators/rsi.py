"""RSI(14) indicator using Wilder smoothing. Implements spec §4.8."""
from __future__ import annotations

import pandas as pd


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return RSI Series using Wilder exponential smoothing (alpha = 1/period).

    No look-ahead: value at T uses only bars ≤ T.
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()

    rs = avg_gain / avg_loss.where(avg_loss != 0, other=float("inf"))
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi.name = "rsi"
    return rsi

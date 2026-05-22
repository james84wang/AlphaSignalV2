"""MACD (12/26/9) indicator. Implements spec §4.7."""
from __future__ import annotations

import pandas as pd


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Return DataFrame with columns: macd_line, macd_signal, macd_hist.

    No look-ahead: each value at T uses only bars ≤ T.
    """
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    result = pd.DataFrame(index=df.index)
    result["macd_line"] = ema_fast - ema_slow
    result["macd_signal"] = result["macd_line"].ewm(span=signal, adjust=False).mean()
    result["macd_hist"] = result["macd_line"] - result["macd_signal"]
    return result

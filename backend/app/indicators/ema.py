"""EMA computation: 20/50/100/200 + EMA200 slope. Implements spec §4.5 and §3."""
from __future__ import annotations

import pandas as pd


def compute_emas(
    df: pd.DataFrame,
    periods: list[int] = (20, 50, 100, 200),
    slope_lookback: int = 20,
) -> pd.DataFrame:
    """Return DataFrame with columns ema_{p} for each period and 'ema200_slope'.

    ema200_slope: +1 (rising), 0 (flat/insufficient data), -1 (falling) per §3.
    No look-ahead: each EMA at bar T uses only bars ≤ T.
    """
    result = pd.DataFrame(index=df.index)
    for p in periods:
        result[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()

    if 200 in list(periods):
        ema200 = result["ema_200"]
        diff = ema200 - ema200.shift(slope_lookback)
        result["ema200_slope"] = diff.map(
            lambda x: 0 if pd.isna(x) else (1 if x > 0 else (-1 if x < 0 else 0))
        )
    else:
        result["ema200_slope"] = 0

    return result

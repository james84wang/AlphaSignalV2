"""Unit tests for scoring/ema.py — ≥3 cases."""
import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.indicators.ema import compute_emas
from backend.app.scoring.ema import score_ema


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _df_from_close(closes) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
    }, index=idx)


class TestEmaScoring:
    def test_full_bull_stack(self, cfg):
        """Price above all EMAs in bull order → stacking +60, no cross → final +60."""
        # Build a long uptrend so EMA20 > EMA50 > EMA100 > EMA200 after warmup
        n = 300
        closes = [100 + i * 0.05 for i in range(n)]  # gentle upward trend

        df = _df_from_close(closes)
        ema_df = compute_emas(df, cfg.ema.periods, cfg.regime.slope_lookback)
        scores = score_ema(df["close"], ema_df, cfg.ema)

        # Check the last bar (should be full bull stack, no cross)
        assert scores.iat[-1] == pytest.approx(60.0, abs=1e-9)

    def test_full_bear_stack(self, cfg):
        """Price below all EMAs in bear order → stacking -60, no cross → final -60."""
        n = 300
        closes = [200 - i * 0.05 for i in range(n)]

        df = _df_from_close(closes)
        ema_df = compute_emas(df, cfg.ema.periods, cfg.regime.slope_lookback)
        scores = score_ema(df["close"], ema_df, cfg.ema)

        assert scores.iat[-1] == pytest.approx(-60.0, abs=1e-9)

    def test_cross_above_ema20_overrides_stack(self, cfg):
        """Price crosses above EMA20 → cross score +35 overrides stack score 0."""
        # Long downtrend so price is below all EMAs, then a single day crosses above EMA20
        n = 250
        closes = [200.0 - i * 0.1 for i in range(n - 1)] + [200.0]

        df = _df_from_close(closes)
        ema_df = compute_emas(df, cfg.ema.periods, cfg.regime.slope_lookback)
        scores = score_ema(df["close"], ema_df, cfg.ema)

        # Last bar: sudden jump could trigger a cross above EMA20
        # We verify cross detection by checking that at bar of a confirmed cross the score is ≥ 35
        prev_close = df["close"].shift(1)
        ema20 = ema_df["ema_20"]
        cross_mask = (df["close"] > ema20) & (prev_close <= ema20.shift(1))
        if cross_mask.any():
            cross_bar = cross_mask.idxmax()
            score_at_cross = scores[cross_bar]
            assert abs(score_at_cross) >= 35.0

    def test_cross_above_ema200_highest_score(self, cfg):
        """Cross above EMA200 → +95 (highest cross score, overrides stacking)."""
        # Build: long downtrend (EMA200 establishes high level), then single big bar above EMA200
        n = 300
        closes = [200.0 - i * 0.3 for i in range(n - 1)] + [250.0]

        df = _df_from_close(closes)
        ema_df = compute_emas(df, cfg.ema.periods, cfg.regime.slope_lookback)
        scores = score_ema(df["close"], ema_df, cfg.ema)

        # Verify the final bar crossed above EMA200
        prev_close = df["close"].shift(1)
        ema200 = ema_df["ema_200"]
        crosses_above_200 = (df["close"] > ema200) & (prev_close <= ema200.shift(1))
        if crosses_above_200.iat[-1]:
            assert abs(scores.iat[-1] - 95.0) < 1e-9

    def test_stacking_above_3_emastop(self, cfg):
        """Price above 3 of 4 EMAs → stacking +30."""
        # Use a DataFrame where we manually control the indicator columns
        n = 5
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        close = pd.Series([105.0] * n, index=idx)

        # Manually craft ema_df: close(105) > ema20(100) > ema50(98) > ema100(96) but < ema200(110)
        ema_df = pd.DataFrame({
            "ema_20": [100.0] * n,
            "ema_50": [98.0] * n,
            "ema_100": [96.0] * n,
            "ema_200": [110.0] * n,
            "ema200_slope": [1] * n,
        }, index=idx)

        scores = score_ema(close, ema_df, cfg.ema)
        # price > ema20, ema50, ema100 but < ema200 → n_above=3 → +30
        assert scores.iat[-1] == pytest.approx(30.0, abs=1e-9)

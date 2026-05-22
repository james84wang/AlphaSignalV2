"""Unit tests for scoring/rsi.py — ≥3 cases."""
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.scoring.rsi import score_rsi


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _rsi_series(*values) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(list(values), index=idx, dtype=float)


class TestRsiScoring:
    def test_crosses_up_30_exits_oversold(self, cfg):
        """RSI was ≤ 30 last bar, now > 30 → crosses_up_30 → +70."""
        rsi = _rsi_series(28.0, 29.0, 30.0, 31.0)  # last bar crosses UP through 30
        scores = score_rsi(rsi, cfg.rsi)
        assert abs(scores.iat[-1] - 70.0) < 1e-9

    def test_crosses_down_70_exits_overbought(self, cfg):
        """RSI was ≥ 70 last bar, now < 70 → crosses_down_70 → -70."""
        rsi = _rsi_series(72.0, 71.0, 70.0, 69.0)
        scores = score_rsi(rsi, cfg.rsi)
        assert abs(scores.iat[-1] - (-70.0)) < 1e-9

    def test_below_30_rising(self, cfg):
        """RSI < 30, rising → +40."""
        rsi = _rsi_series(25.0, 26.0, 27.0)  # stays below 30, rising
        scores = score_rsi(rsi, cfg.rsi)
        assert abs(scores.iat[-1] - 40.0) < 1e-9

    def test_between_50_70_rising(self, cfg):
        """RSI in 50–70, rising → +25."""
        rsi = _rsi_series(55.0, 57.0, 60.0)
        scores = score_rsi(rsi, cfg.rsi)
        assert abs(scores.iat[-1] - 25.0) < 1e-9

    def test_above_70_falling(self, cfg):
        """RSI > 70, falling → -40."""
        rsi = _rsi_series(80.0, 78.0, 75.0)  # stays > 70, falling
        scores = score_rsi(rsi, cfg.rsi)
        assert abs(scores.iat[-1] - (-40.0)) < 1e-9

    def test_above_70_rising(self, cfg):
        """RSI > 70, rising → +10."""
        rsi = _rsi_series(71.0, 73.0, 75.0)
        scores = score_rsi(rsi, cfg.rsi)
        assert abs(scores.iat[-1] - 10.0) < 1e-9

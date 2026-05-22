"""Unit tests for scoring/volume.py — ≥3 cases."""
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.scoring.volume import score_volume


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _inputs(closes, opens, volumes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return (
        pd.Series(closes, index=idx),
        pd.Series(opens,  index=idx),
        pd.Series(volumes, index=idx),
    )


class TestVolumeScoring:
    def test_bullish_candle_high_rv(self, cfg):
        """Bullish candle with RV ≈ 3.5× → +80."""
        # 30 identical volume bars to establish avg, then a 3.5× bar
        avg_vol = 1_000_000
        test_vol = int(avg_vol * 3.5)

        n = 31
        closes  = [101.0] * 30 + [102.0]
        opens   = [100.0] * n
        volumes = [avg_vol] * 30 + [test_vol]

        c, o, v = _inputs(closes, opens, volumes)
        pattern = pd.Series(["no_pattern"] * n, index=c.index)

        scores = score_volume(c, o, v, pattern, cfg.volume)
        # RV = test_vol / ((30*avg_vol + test_vol)/31) ≈ 3.42, bucket 3.0-5.0 → +80
        assert scores.iat[-1] > 0  # must be positive (bullish candle + high volume)
        assert abs(scores.iat[-1] - 80.0) < 1e-9

    def test_bearish_candle_high_rv_inverts_sign(self, cfg):
        """Bearish candle with RV ≈ 3.5× → -80 (sign inverted)."""
        avg_vol = 1_000_000
        test_vol = int(avg_vol * 3.5)

        n = 31
        closes  = [99.0] * 30 + [98.0]   # close < open → bearish
        opens   = [100.0] * n
        volumes = [avg_vol] * 30 + [test_vol]

        c, o, v = _inputs(closes, opens, volumes)
        pattern = pd.Series(["no_pattern"] * n, index=c.index)

        scores = score_volume(c, o, v, pattern, cfg.volume)
        assert scores.iat[-1] < 0
        assert abs(scores.iat[-1] - (-80.0)) < 1e-9

    def test_doji_pattern_scores_zero_regardless_of_rv(self, cfg):
        """Doji/spinning top candle → sub-score = 0 regardless of volume."""
        avg_vol = 1_000_000
        test_vol = avg_vol * 10  # extreme volume

        n = 31
        closes  = [101.0] * 30 + [101.0]  # close > open but pattern is doji
        opens   = [100.0] * n
        volumes = [avg_vol] * 30 + [test_vol]

        c, o, v = _inputs(closes, opens, volumes)
        # Force neutral pattern
        pattern = pd.Series(["no_pattern"] * 30 + ["bullish_doji"], index=c.index)

        scores = score_volume(c, o, v, pattern, cfg.volume)
        assert scores.iat[-1] == 0.0

    def test_bullish_low_rv_penalised(self, cfg):
        """Bullish candle with RV < 0.8× → negative score (weak conviction)."""
        avg_vol = 1_000_000
        test_vol = int(avg_vol * 0.6)  # 0.6× → bucket 0.5–0.8 → -15

        n = 31
        closes  = [101.0] * 30 + [102.0]
        opens   = [100.0] * n
        volumes = [avg_vol] * 30 + [test_vol]

        c, o, v = _inputs(closes, opens, volumes)
        pattern = pd.Series(["no_pattern"] * n, index=c.index)

        scores = score_volume(c, o, v, pattern, cfg.volume)
        assert scores.iat[-1] < 0

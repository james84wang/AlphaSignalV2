"""Unit tests for scoring/support_resistance.py — ≥3 cases."""
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.scoring.support_resistance import score_sr


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _sr_df(support=None, resistance=None, n=1) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "support_level": [support] * n,
        "resistance_level": [resistance] * n,
    }, index=idx)


def _series(values, start="2024-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx)


class TestSrScoring:
    def test_strong_bounce_off_support(self, cfg):
        """Low touches support, close ≥ midpoint, range > avg range → +80."""
        n = 30
        # 29 normal bars with avg range ~2, then a bounce bar
        avg_vol = 1_000_000
        highs   = _series([102.0] * 29 + [104.0])
        lows    = _series([100.0] * 29 + [99.0])   # low touches support at 99
        closes  = _series([101.0] * 29 + [103.0])  # close=103 ≥ midpoint=(99+104)/2=101.5 ✓
        opens   = _series([101.0] * n)
        volumes = _series([avg_vol] * n)
        sr = _sr_df(support=99.5, resistance=110.0, n=n)  # support ≈ 99 (low touches)

        scores = score_sr(closes, highs, lows, volumes, sr, cfg.sr)
        assert scores.iat[-1] == pytest.approx(80.0, abs=1e-9)

    def test_breakout_above_resistance(self, cfg):
        """Close above resistance with volume ≥ 1.5× avg → +85."""
        avg_vol = 1_000_000
        test_vol = int(avg_vol * 2.0)  # 2× → meets threshold

        n = 31
        highs   = _series([102.0] * 30 + [115.0])
        lows    = _series([100.0] * n)
        closes  = _series([101.0] * 30 + [114.0])   # breaks above resistance at 110
        opens   = _series([100.0] * n)
        volumes = _series([avg_vol] * 30 + [test_vol])
        sr = _sr_df(support=95.0, resistance=110.0, n=n)

        scores = score_sr(closes, highs, lows, volumes, sr, cfg.sr)
        assert scores.iat[-1] == pytest.approx(85.0, abs=1e-9)

    def test_breakdown_below_support(self, cfg):
        """Close below support with volume ≥ 1.5× avg → -85."""
        avg_vol = 1_000_000
        test_vol = int(avg_vol * 2.0)

        n = 31
        highs   = _series([102.0] * n)
        lows    = _series([100.0] * 30 + [89.0])
        closes  = _series([101.0] * 30 + [90.0])  # breaks below support at 95
        opens   = _series([101.0] * n)
        volumes = _series([avg_vol] * 30 + [test_vol])
        sr = _sr_df(support=95.0, resistance=110.0, n=n)

        scores = score_sr(closes, highs, lows, volumes, sr, cfg.sr)
        assert scores.iat[-1] == pytest.approx(-85.0, abs=1e-9)

    def test_no_interaction(self, cfg):
        """Price away from all levels → 0."""
        n = 5
        highs   = _series([102.0] * n)
        lows    = _series([100.0] * n)
        closes  = _series([101.0] * n)
        opens   = _series([101.0] * n)
        volumes = _series([1_000_000] * n)
        sr = _sr_df(support=80.0, resistance=120.0, n=n)  # far from price

        scores = score_sr(closes, highs, lows, volumes, sr, cfg.sr)
        assert scores.iat[-1] == pytest.approx(0.0, abs=1e-9)

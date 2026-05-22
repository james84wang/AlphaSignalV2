"""Unit tests for scoring/p5.py — ≥3 cases."""
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.indicators.pivots import detect_p5_pattern
from backend.app.scoring.p5 import score_p5


def _bars(*rows) -> pd.DataFrame:
    data = [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in rows]
    return pd.DataFrame(data)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


class TestP5Scoring:
    def test_bullish_trend_confirmation(self, cfg):
        """5 bars with HH+HL → bullish_trend_confirmation → +50."""
        df = _bars(
            (99, 101, 98, 100),
            (100, 103, 99, 102),
            (101, 105, 100, 104),
            (103, 107, 102, 106),
            (105, 109, 104, 108),
        )
        patterns = detect_p5_pattern(df)
        scores = score_p5(patterns, cfg.p5)
        assert patterns.iat[4] == "bullish_trend_confirmation"
        assert abs(scores.iat[4] - 50.0) < 1e-9

    def test_bearish_trend_confirmation(self, cfg):
        """5 bars with LH+LL → bearish_trend_confirmation → -50."""
        df = _bars(
            (108, 110, 107, 109),
            (106, 108, 105, 107),
            (104, 106, 103, 105),
            (102, 104, 101, 103),
            (100, 102, 99, 101),
        )
        patterns = detect_p5_pattern(df)
        scores = score_p5(patterns, cfg.p5)
        assert patterns.iat[4] == "bearish_trend_confirmation"
        assert abs(scores.iat[4] - (-50.0)) < 1e-9

    def test_major_bullish_reversal(self, cfg):
        """Clear 5-bar trough followed by strong close → major_bullish_reversal → +85."""
        # b0: high close, b1-b3: declining (trough at b2/b3), b4: highest close
        df = _bars(
            (105, 108, 104, 106),   # start high
            (103, 106, 102, 104),   # declining
            (100, 103, 99, 101),    # trough interior
            (99,  102, 98, 100),    # trough interior (lowest)
            (101, 110, 100, 109),   # strong recovery — highest close
        )
        patterns = detect_p5_pattern(df)
        scores = score_p5(patterns, cfg.p5)
        assert patterns.iat[4] == "major_bullish_reversal"
        assert abs(scores.iat[4] - 85.0) < 1e-9

    def test_major_bearish_reversal(self, cfg):
        """Clear 5-bar peak followed by strong decline → major_bearish_reversal → -85."""
        df = _bars(
            (100, 103, 99, 101),    # start low
            (102, 105, 101, 103),   # rising
            (104, 107, 103, 106),   # peak interior
            (105, 108, 104, 107),   # peak interior (highest)
            (104, 106, 96, 97),     # strong decline — lowest close
        )
        patterns = detect_p5_pattern(df)
        scores = score_p5(patterns, cfg.p5)
        assert patterns.iat[4] == "major_bearish_reversal"
        assert abs(scores.iat[4] - (-85.0)) < 1e-9

    def test_first_four_bars_no_pattern(self, cfg):
        """First 4 bars cannot form a 5-bar pattern → no_pattern → 0."""
        df = _bars(
            (99, 101, 98, 100),
            (100, 103, 99, 102),
            (101, 105, 100, 104),
            (103, 107, 102, 106),
            (105, 109, 104, 108),
        )
        patterns = detect_p5_pattern(df)
        scores = score_p5(patterns, cfg.p5)
        for i in range(4):
            assert patterns.iat[i] == "no_pattern"
            assert scores.iat[i] == 0.0

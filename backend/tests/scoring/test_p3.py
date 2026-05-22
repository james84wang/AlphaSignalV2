"""Unit tests for scoring/p3.py — ≥3 cases."""
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.indicators.pivots import detect_p3_pattern
from backend.app.scoring.p3 import score_p3


def _bars(*rows) -> pd.DataFrame:
    """Build a DataFrame from (open, high, low, close) tuples."""
    data = [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in rows]
    return pd.DataFrame(data)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


class TestP3Scoring:
    def test_continuation_up(self, cfg):
        """Three progressively higher closes → continuation_up → +30.

        Prior bars have tall upper shadows (high >> close) so close stays BELOW
        prior highs (no breakout), and no lower wicks (no reversal buying tails).
        """
        # b0 close=101, high=104; b1 close=102, high=105; b2 close=103 ≤ max(104,105)=105
        df = _bars(
            (100, 104, 100, 101),  # high=104, lower_wick=0, lt0=0
            (101, 105, 101, 102),  # high=105, lower_wick=0, lt1=0
            (102, 106, 102, 103),  # close=103 < max(104,105)=105 → no breakout
        )
        patterns = detect_p3_pattern(df)
        scores = score_p3(patterns, cfg.p3)
        assert patterns.iat[2] == "continuation_up", (
            f"Expected continuation_up, got {patterns.iat[2]}"
        )
        assert abs(scores.iat[2] - 30.0) < 1e-9

    def test_continuation_down(self, cfg):
        """Three progressively lower closes → continuation_down → -30.

        Prior bars have no upper wicks (no reversal selling tails) and current
        close stays above the prior lows (no breakdown).
        """
        # b0 low=100, high=104 (=open=close), ut0=0; b1 low=99, ut1=0
        # b2 close=102 < 103 < 104 and 102 > min(100,99)=99 → no breakdown
        df = _bars(
            (104, 104, 100, 104),  # upper_wick=0, low=100
            (103, 103, 99, 103),   # upper_wick=0, low=99
            (103, 103, 98, 102),   # close=102 < 103 < 104; 102 > 99 → no breakdown
        )
        patterns = detect_p3_pattern(df)
        scores = score_p3(patterns, cfg.p3)
        assert patterns.iat[2] == "continuation_down", (
            f"Expected continuation_down, got {patterns.iat[2]}"
        )
        assert abs(scores.iat[2] - (-30.0)) < 1e-9

    def test_bullish_breakout_above_resistance(self, cfg):
        """Current close above both prior highs → bullish_breakout_above_resistance → +60.

        Prior bars have no lower wicks so buying-tail condition doesn't fire first.
        """
        # prior highs: 101, 102; current close = 105 > max(101, 102) = 102
        df = _bars(
            (100, 101, 100, 101),  # lower_wick=0, lt0=0
            (101, 102, 101, 102),  # lower_wick=0, lt1=0
            (102, 106, 102, 105),  # close=105 > max(101, 102) ✓
        )
        patterns = detect_p3_pattern(df)
        scores = score_p3(patterns, cfg.p3)
        assert patterns.iat[2] == "bullish_breakout_above_resistance", (
            f"Expected bullish_breakout_above_resistance, got {patterns.iat[2]}"
        )
        assert abs(scores.iat[2] - 60.0) < 1e-9

    def test_bearish_reversal_at_resistance(self, cfg):
        """Current closes lowest with upper wicks on prior bars → bearish_reversal_at_resistance → -70."""
        # Prior bars push up with selling tails; current closes below both
        # b0: open=102, high=108, low=101, close=103 — upper wick = 108-103=5, range=7, tail_pct≈0.71
        # b1: open=103, high=107, low=102, close=104 — upper wick = 107-104=3, range=5, tail_pct=0.6
        # b2: current closes at 101 < 103 and < 104
        df = _bars(
            (102, 108, 101, 103),
            (103, 107, 102, 104),
            (104, 105, 100, 101),
        )
        patterns = detect_p3_pattern(df)
        scores = score_p3(patterns, cfg.p3)
        assert patterns.iat[2] == "bearish_reversal_at_resistance"
        assert abs(scores.iat[2] - (-70.0)) < 1e-9

    def test_no_pattern_bars_insufficient(self, cfg):
        """First two bars cannot form a 3-bar pattern → no_pattern → 0."""
        df = _bars(
            (100, 102, 99, 101),
            (101, 103, 100, 102),
            (102, 104, 101, 103),  # continuation_up, not no_pattern
        )
        patterns = detect_p3_pattern(df)
        scores = score_p3(patterns, cfg.p3)
        # First two bars are always no_pattern
        assert patterns.iat[0] == "no_pattern"
        assert patterns.iat[1] == "no_pattern"
        assert scores.iat[0] == 0.0
        assert scores.iat[1] == 0.0

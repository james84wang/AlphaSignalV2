"""Unit tests for scoring/candlestick.py — ≥3 cases per spec acceptance criterion #5."""
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.indicators.candlestick import detect_candlestick_pattern
from backend.app.scoring.candlestick import score_candlestick


def _bar(o: float, h: float, l: float, c: float) -> pd.DataFrame:
    """Build a minimal single-bar DataFrame."""
    return pd.DataFrame({"open": [o], "high": [h], "low": [l], "close": [c]})


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ── Pattern detection helpers ─────────────────────────────────────────────────

class TestCandlestickPatternDetection:
    def test_long_bullish_candle(self):
        """Body ≥ 70% of range, green → long_bullish_candle."""
        df = _bar(100, 109, 99, 108)  # body=8, range=10, body_pct=0.8
        pattern = detect_candlestick_pattern(df).iat[0]
        assert pattern == "long_bullish_candle"

    def test_green_hammer(self):
        """Green body near top (body_mid_pct ≥ 2/3), long lower wick."""
        # range=10 (100–110), body=(107,109), body_mid=108, body_mid_pct=0.8
        # lower_wick=107-100=7, body=2, 7≥2*2 ✓; upper_wick=110-109=1≤2 ✓
        df = _bar(107, 110, 100, 109)
        pattern = detect_candlestick_pattern(df).iat[0]
        assert pattern == "green_hammer"

    def test_long_bearish_candle(self):
        """Body ≥ 70% of range, red → long_bearish_candle."""
        df = _bar(108, 109, 99, 100)  # body=8, range=10, body_pct=0.8
        pattern = detect_candlestick_pattern(df).iat[0]
        assert pattern == "long_bearish_candle"

    def test_no_pattern(self):
        """Indeterminate bar → no_pattern."""
        # Small body in middle, small wicks — not a hammer, not a doji, not spinning top
        df = _bar(100, 103, 98, 101)  # body=1, range=5, body_pct=0.2 < 0.30 BUT
        # lower_wick=min(100,101)-98=2, upper_wick=103-101=2, body_mid=(100+101)/2-98=2.5/5=0.5
        # body=1, spinning top check: lower_wick(2)>body(1) ✓, upper_wick(2)>body(1) ✓
        # so this should be a spinning top, not no_pattern
        # Let's use a bar where none of the conditions match
        # Narrow range, medium body that's 40% of range → not long, not small, not doji
        df = _bar(100, 102.5, 100, 101)  # body=1, range=2.5, body_pct=0.4, not long (< 0.70)
        # lower_wick = 100 - 100 = 0, upper_wick = 2.5 - 101 = 1.5
        # body_mid = (100+101)/2 = 100.5, body_mid_pct = (100.5-100)/2.5 = 0.2 ≤ 1/3
        # Not hammer (body_mid_pct < 2/3), not inverted hammer (upper_wick=1.5 < 2*body=2)
        # Not spinning top (lower_wick=0 not > body=1)
        # Not doji (body_pct=0.4 > 0.05)
        pattern = detect_candlestick_pattern(df).iat[0]
        assert pattern == "no_pattern"

    def test_inverted_red_hammer_shooting_star(self):
        """Red body in lower 1/3, long upper wick → inverted_red_hammer."""
        # low=100, high=110, open=103, close=101 → red body
        # range=10, body_mid=(103+101)/2=102, body_mid_pct=(102-100)/10=0.2 ≤ 1/3 ✓
        # upper_wick=110-103=7, body=2, 7≥2*2 ✓; lower_wick=101-100=1≤2 ✓
        df = _bar(103, 110, 100, 101)
        pattern = detect_candlestick_pattern(df).iat[0]
        assert pattern == "inverted_red_hammer"


# ── Scoring ───────────────────────────────────────────────────────────────────

class TestCandlestickScoring:
    def test_green_hammer_at_support_gets_multiplier(self, cfg):
        """Green hammer at S/R level multiplied by 1.2, capped at 100."""
        df = _bar(107, 110, 100, 109)
        pattern = detect_candlestick_pattern(df)
        at_sr = pd.Series([True])

        sub = score_candlestick(pattern, at_sr, cfg.candlestick).iat[0]
        expected = min(80 * 1.2, 100)  # = 96.0
        assert abs(sub - expected) < 1e-9

    def test_long_bullish_no_multiplier(self, cfg):
        """Long bullish candle not at S/R → raw score."""
        df = _bar(100, 109, 99, 108)
        pattern = detect_candlestick_pattern(df)
        at_sr = pd.Series([False])

        sub = score_candlestick(pattern, at_sr, cfg.candlestick).iat[0]
        assert abs(sub - 90.0) < 1e-9

    def test_long_bearish_score(self, cfg):
        """Long bearish candle → -90."""
        df = _bar(108, 109, 99, 100)
        pattern = detect_candlestick_pattern(df)
        at_sr = pd.Series([False])

        sub = score_candlestick(pattern, at_sr, cfg.candlestick).iat[0]
        assert abs(sub - (-90.0)) < 1e-9

    def test_no_pattern_score_zero(self, cfg):
        """No pattern → 0 score."""
        df = _bar(100, 102.5, 100, 101)
        pattern = detect_candlestick_pattern(df)
        at_sr = pd.Series([False])

        sub = score_candlestick(pattern, at_sr, cfg.candlestick).iat[0]
        assert sub == 0.0

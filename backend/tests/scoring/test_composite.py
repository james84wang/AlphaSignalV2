"""Composite engine tests — golden Example_Calc test + look-ahead verification."""
import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.scoring.composite import run_engine, score_bar


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ── Golden test ───────────────────────────────────────────────────────────────

class TestGoldenExampleCalc:
    """Reproduces the Example_Calc tab from trading_strategy_template.xlsx.

    Sub-scores from the xlsx:
      Candlestick = 85  (Green hammer at support)
      P3          = 70  (Bullish reversal at support)
      P5          = 85  (Major bullish reversal)
      Volume      = 60  (2.5× avg on bullish candle)
      EMA         = 35  (Crossed above EMA20)
      S/R         = 80  (Bounced off support)
      MACD        = 55  (Golden cross + above zero + contracting green)
      RSI         = 40  (RSI < 30 and rising)

    Expected composite = 12*85/100 + 8*70/100 + 12*85/100 + 10*60/100
                       + 15*35/100 + 15*80/100 + 18*55/100 + 10*40/100
                       = 10.2 + 5.6 + 10.2 + 6.0 + 5.25 + 12.0 + 9.9 + 4.0
                       = 63.15  → HOLD
    """

    def test_composite_equals_63_15(self, cfg):
        sub_scores = {
            "candlestick": 85.0,
            "p3": 70.0,
            "p5": 85.0,
            "volume": 60.0,
            "ema": 35.0,
            "sr": 80.0,
            "macd": 55.0,
            "rsi": 40.0,
        }
        regime = {"long_allowed": True, "short_allowed": False}
        result = score_bar(sub_scores, cfg.weights, regime, cfg.thresholds)

        assert abs(result["composite"] - 63.15) < 1e-9, (
            f"Expected 63.15, got {result['composite']}"
        )

    def test_signal_is_hold(self, cfg):
        sub_scores = {
            "candlestick": 85.0,
            "p3": 70.0,
            "p5": 85.0,
            "volume": 60.0,
            "ema": 35.0,
            "sr": 80.0,
            "macd": 55.0,
            "rsi": 40.0,
        }
        regime = {"long_allowed": True, "short_allowed": False}
        result = score_bar(sub_scores, cfg.weights, regime, cfg.thresholds)

        assert result["signal"] == "Hold"

    def test_all_components_present_in_output(self, cfg):
        """Auditable output must include every component sub-score."""
        sub_scores = {
            "candlestick": 85.0,
            "p3": 70.0,
            "p5": 85.0,
            "volume": 60.0,
            "ema": 35.0,
            "sr": 80.0,
            "macd": 55.0,
            "rsi": 40.0,
        }
        regime = {"long_allowed": True, "short_allowed": False}
        result = score_bar(sub_scores, cfg.weights, regime, cfg.thresholds)

        expected_keys = set(sub_scores.keys())
        assert set(result["components"].keys()) == expected_keys
        for name, data in result["components"].items():
            assert "sub" in data
            assert "weight" in data
            assert "weighted" in data


# ── Regime gate test ──────────────────────────────────────────────────────────

class TestRegimeGate:
    def test_positive_composite_gated_to_zero_when_long_not_allowed(self, cfg):
        """Spec §5: if raw_composite > 0 and not long_allowed → composite = 0."""
        sub_scores = {k: 50.0 for k in
                      ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]}
        regime = {"long_allowed": False, "short_allowed": True}
        result = score_bar(sub_scores, cfg.weights, regime, cfg.thresholds)

        assert result["composite"] == 0.0
        assert result["signal"] == "Hold"

    def test_negative_composite_gated_to_zero_when_short_not_allowed(self, cfg):
        """Spec §5: if raw_composite < 0 and not short_allowed → composite = 0."""
        sub_scores = {k: -50.0 for k in
                      ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]}
        regime = {"long_allowed": True, "short_allowed": False}
        result = score_bar(sub_scores, cfg.weights, regime, cfg.thresholds)

        assert result["composite"] == 0.0
        assert result["signal"] == "Hold"

    def test_both_allowed_passes_through(self, cfg):
        """When both sides allowed, composite passes through unchanged."""
        sub_scores = {k: 50.0 for k in
                      ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]}
        regime = {"long_allowed": True, "short_allowed": True}
        result = score_bar(sub_scores, cfg.weights, regime, cfg.thresholds)

        assert result["composite"] > 0.0


# ── Signal threshold tests ────────────────────────────────────────────────────

class TestSignalThresholds:
    def test_strong_buy(self, cfg):
        regime = {"long_allowed": True, "short_allowed": True}
        result = score_bar(
            {k: 90.0 for k in ["candlestick","p3","p5","volume","ema","sr","macd","rsi"]},
            cfg.weights, regime, cfg.thresholds,
        )
        assert result["signal"] == "Strong Buy"

    def test_strong_sell(self, cfg):
        regime = {"long_allowed": True, "short_allowed": True}
        result = score_bar(
            {k: -90.0 for k in ["candlestick","p3","p5","volume","ema","sr","macd","rsi"]},
            cfg.weights, regime, cfg.thresholds,
        )
        assert result["signal"] == "Strong Sell"


# ── Look-ahead test ───────────────────────────────────────────────────────────

class TestNoLookahead:
    """Prove signal for bar T is unchanged when future bars are deleted (spec §8 #2)."""

    def _make_df(self, n: int, seed: int = 42) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        prices = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
        opens  = prices + rng.uniform(-0.2, 0.2, n)
        highs  = np.maximum(opens, prices) + rng.uniform(0, 0.5, n)
        lows   = np.minimum(opens, prices) - rng.uniform(0, 0.5, n)
        vols   = rng.integers(500_000, 5_000_000, n)
        idx    = pd.date_range("2023-01-01", periods=n, freq="B")
        return pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": prices, "volume": vols},
            index=idx,
        )

    def test_signal_unchanged_after_truncation(self, cfg):
        """Signal at bar T must be identical whether or not bars T+1…T+N exist."""
        n_full = 80
        n_truncated = 70

        df_full      = self._make_df(n_full)
        df_truncated = df_full.iloc[:n_truncated]

        results_full      = run_engine(df_full, cfg)
        results_truncated = run_engine(df_truncated, cfg)

        # Compare the last bar of the truncated run against the same date in the full run
        last_date_trunc = df_truncated.index[-1]
        full_at_trunc = next(
            r for r in results_full if r["date"] == str(last_date_trunc.date())
        )
        trunc_last = results_truncated[-1]

        assert abs(full_at_trunc["composite"] - trunc_last["composite"]) < 1e-9, (
            f"Look-ahead bias detected: full={full_at_trunc['composite']}, "
            f"truncated={trunc_last['composite']}"
        )
        assert full_at_trunc["signal"] == trunc_last["signal"]

    def test_multiple_truncation_points(self, cfg):
        """Verify no look-ahead at several different cutoff dates."""
        n_full = 100
        df_full = self._make_df(n_full, seed=123)
        results_full = run_engine(df_full, cfg)

        for cutoff in [60, 70, 80, 90]:
            df_trunc = df_full.iloc[:cutoff]
            results_trunc = run_engine(df_trunc, cfg)

            last_date = df_trunc.index[-1]
            full_bar = next(
                r for r in results_full if r["date"] == str(last_date.date())
            )
            trunc_bar = results_trunc[-1]

            assert abs(full_bar["composite"] - trunc_bar["composite"]) < 1e-9, (
                f"Look-ahead at cutoff={cutoff}: full={full_bar['composite']}, "
                f"trunc={trunc_bar['composite']}"
            )

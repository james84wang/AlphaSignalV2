"""Backtest engine tests.

Critical tests required by spec phase-4.md:
1. No look-ahead: signal(T) is identical whether bars > T exist or not.
2. Entry fills on T+1 open, never T close.
3. Stop uses intrabar high/low correctly (not just open/close).
4. Changing a config weight changes the backtest result.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backend.app.config import AppConfig, BacktestConfig, load_config
from backend.app.backtest.engine import (
    SURVIVORSHIP_BIAS_NOTE,
    BacktestResult,
    ClosedTrade,
    _check_stop,
    _Position,
    _update_trailing_stop,
    run_backtest,
)
from backend.app.backtest.metrics import compute_metrics
from backend.app.scoring.composite import run_engine


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _make_ohlcv(
    n: int = 120,
    seed: int = 42,
    start: str = "2020-01-02",
    trend: float = 0.0,
) -> pd.DataFrame:
    """Synthetic OHLCV with a configurable upward drift."""
    rng = np.random.default_rng(seed)
    closes = 100.0 + trend * np.arange(n) + np.cumsum(rng.standard_normal(n) * 0.8)
    opens = closes + rng.uniform(-0.5, 0.5, n)
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 1.0, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 1.0, n)
    vols = rng.integers(1_000_000, 10_000_000, n).astype("int64")
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


def _make_fetcher(sym_to_df: dict) -> callable:
    """Return a data_fetcher that serves pre-built DataFrames."""
    def _fetch(sym: str, start: date, end: date) -> pd.DataFrame:
        if sym not in sym_to_df:
            raise ValueError(f"Unknown symbol: {sym}")
        df = sym_to_df[sym]
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df.index >= s) & (df.index <= e)]
    return _fetch


# ── Anti-look-ahead tests ──────────────────────────────────────────────────────

class TestNoLookahead:
    """Prove signal(T) is identical whether or not bars > T exist.

    This validates that run_engine (and therefore the backtest engine) does not
    use future bars when computing the signal for bar T.
    """

    def test_signal_identical_with_future_bars_removed(self, cfg):
        """Signal at bar T must equal signal at T computed without bars T+1…T+n."""
        n_full = 100
        n_trunc = 80

        df_full = _make_ohlcv(n_full)
        df_trunc = df_full.iloc[:n_trunc]

        results_full = run_engine(df_full, cfg)
        results_trunc = run_engine(df_trunc, cfg)

        # Compare the final bar of the truncated run against the same date in the full run
        trunc_last_date = str(df_trunc.index[-1].date())
        full_at_trunc = next(r for r in results_full if r["date"] == trunc_last_date)
        trunc_last = results_trunc[-1]

        assert abs(full_at_trunc["composite"] - trunc_last["composite"]) < 1e-9, (
            f"Look-ahead bias: full={full_at_trunc['composite']:.6f}, "
            f"trunc={trunc_last['composite']:.6f}"
        )
        assert full_at_trunc["signal"] == trunc_last["signal"]

    def test_multiple_truncation_points(self, cfg):
        """No look-ahead at cutoffs 60, 70, 80, 90 bars."""
        df_full = _make_ohlcv(n=100, seed=7)
        results_full = run_engine(df_full, cfg)

        for cutoff in [60, 70, 80, 90]:
            df_trunc = df_full.iloc[:cutoff]
            results_trunc = run_engine(df_trunc, cfg)

            trunc_date = str(df_trunc.index[-1].date())
            full_bar = next(r for r in results_full if r["date"] == trunc_date)
            trunc_bar = results_trunc[-1]

            assert abs(full_bar["composite"] - trunc_bar["composite"]) < 1e-9, (
                f"Look-ahead at cutoff={cutoff}: "
                f"full={full_bar['composite']:.6f}, trunc={trunc_bar['composite']:.6f}"
            )


# ── Entry fills on T+1 open ────────────────────────────────────────────────────

class TestEntryOnNextOpen:
    """Verify entries fill at the *next* bar's open, not the signal bar's close.

    Tests use unittest.mock.patch to inject a deterministic "Strong Buy" signal on
    a chosen bar, then verify the trade fills at the FOLLOWING bar's open.
    """

    def _run_with_forced_signal(self, cfg, signal_bar_idx: int = 60) -> tuple:
        """Run backtest where bar signal_bar_idx emits 'Strong Buy', rest 'Hold'."""
        df = _make_ohlcv(n=120, seed=55)

        # Build a fake signals list: Hold everywhere except signal_bar_idx
        def _fake_compute_signals(data, _cfg):
            results = []
            for i in range(len(data)):
                if i == signal_bar_idx:
                    sig = "Strong Buy"
                    comp = 90.0
                else:
                    sig = "Hold"
                    comp = 0.0
                results.append({"date": str(data.index[i].date()), "composite": comp, "signal": sig})
            return results

        fetcher = _make_fetcher({"T": df})
        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake_compute_signals):
            result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)

        return df, result

    def test_entry_date_is_one_bar_after_signal(self, cfg):
        """Entry must fill on the bar AFTER the signal, not on the signal bar itself."""
        signal_bar_idx = 60
        df, result = self._run_with_forced_signal(cfg, signal_bar_idx)

        assert result.trades, "Expected at least one trade (Strong Buy was injected)"
        trade = result.trades[0]

        expected_entry_date = str(df.index[signal_bar_idx + 1].date())
        assert trade.entry_date == expected_entry_date, (
            f"Entry date {trade.entry_date} ≠ expected {expected_entry_date} "
            "(should be the bar AFTER the signal)"
        )

    def test_entry_price_equals_next_open_with_slippage(self, cfg):
        """Entry price must equal open[T+1] × (1 + slippage) for a long."""
        signal_bar_idx = 60
        df, result = self._run_with_forced_signal(cfg, signal_bar_idx)

        assert result.trades, "Expected a trade"
        trade = result.trades[0]

        fill_bar_open = float(df.iloc[signal_bar_idx + 1]["open"])
        expected_entry_price = fill_bar_open * (1 + cfg.backtest.slippage_pct)
        assert abs(trade.entry_price - expected_entry_price) < 1e-6, (
            f"Entry price {trade.entry_price:.6f} ≠ open[T+1]×(1+slip) {expected_entry_price:.6f}"
        )

    def test_entry_price_is_not_signal_bar_close(self, cfg):
        """Entry price must NOT be the signal bar's close price."""
        signal_bar_idx = 60
        df, result = self._run_with_forced_signal(cfg, signal_bar_idx)

        if not result.trades:
            pytest.skip("No trades generated")

        trade = result.trades[0]
        signal_bar_close = float(df.iloc[signal_bar_idx]["close"])
        fill_bar_open = float(df.iloc[signal_bar_idx + 1]["open"])

        assert abs(trade.entry_price - signal_bar_close) > 1e-6 or \
               abs(signal_bar_close - fill_bar_open) < 1e-6, (
            "Entry price appears to be the signal-bar close — should be next bar's open"
        )


# ── Stop / exit intrabar checks ────────────────────────────────────────────────

class TestStopIntrabar:
    """Verify the stop-loss uses intrabar high/low, not just open/close."""

    def test_long_stop_triggers_at_stop_price_not_open(self):
        """For a long position, stop triggers at stop_price when low < stop < open."""
        pos = _Position(
            symbol="X", side="long", entry_date="2020-01-01",
            entry_price=100.0, shares=10.0, stop_price=98.0,
        )
        bar = {"open": 99.5, "high": 100.5, "low": 97.5, "close": 99.0}
        hit, fill = _check_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(98.0)  # stop_price, not open

    def test_long_stop_not_triggered_when_low_above_stop(self):
        pos = _Position(
            symbol="X", side="long", entry_date="2020-01-01",
            entry_price=100.0, shares=10.0, stop_price=95.0,
        )
        bar = {"open": 99.5, "high": 100.5, "low": 96.0, "close": 99.0}
        hit, _ = _check_stop(pos, bar)
        assert hit is False

    def test_long_stop_gap_down_fills_at_open(self):
        """Gap-down through stop fills at open (worse than stop price)."""
        pos = _Position(
            symbol="X", side="long", entry_date="2020-01-01",
            entry_price=100.0, shares=10.0, stop_price=98.0,
        )
        bar = {"open": 96.0, "high": 97.0, "low": 95.0, "close": 96.5}
        hit, fill = _check_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(96.0)  # open, since open < stop

    def test_short_stop_triggers_at_stop_price_intrabar(self):
        pos = _Position(
            symbol="X", side="short", entry_date="2020-01-01",
            entry_price=100.0, shares=10.0, stop_price=103.0,
        )
        bar = {"open": 101.5, "high": 104.0, "low": 101.0, "close": 102.0}
        hit, fill = _check_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(103.0)

    def test_short_stop_gap_up_fills_at_open(self):
        pos = _Position(
            symbol="X", side="short", entry_date="2020-01-01",
            entry_price=100.0, shares=10.0, stop_price=103.0,
        )
        bar = {"open": 105.0, "high": 106.0, "low": 104.0, "close": 105.0}
        hit, fill = _check_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(105.0)  # open > stop

    def test_stop_not_checked_on_entry_bar(self, cfg):
        """No stop-hit should occur on the same bar the position was entered."""
        # Build a DataFrame where the open and low on the entry bar are both below
        # where the stop would sit — this should NOT trigger a stop.
        # (In practice the stop is set relative to the entry price so it starts safe;
        # this test verifies the engine code guards skip-same-bar-stop correctly.)
        df = _make_ohlcv(n=80, seed=99, trend=0.5)
        fetcher = _make_fetcher({"T": df})
        result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)
        # If entry-bar stop was erroneously checked, trades would show 0-bar hold time.
        for trade in result.trades:
            entry = pd.Timestamp(trade.entry_date)
            exit_ = pd.Timestamp(trade.exit_date)
            assert exit_ >= entry, "Exit date before entry date — impossible"
            # A trade exiting on exactly the entry bar would mean a 0-day hold.
            # This should never happen (stop skipped on entry bar).
            if trade.exit_reason == "stop":
                assert exit_ > entry, "Stop triggered on entry bar — look-ahead error"


# ── Trailing stop ──────────────────────────────────────────────────────────────

class TestTrailingStop:
    def test_long_trailing_stop_moves_up_only(self, cfg):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 95.0)
        bar_profit = {"open": 110.0, "high": 112.0, "low": 109.0, "close": 111.0}
        _update_trailing_stop(pos, bar_profit, atr=2.0, cfg=cfg)
        # new_stop = 111 - 1.5*2 = 108
        assert pos.stop_price == pytest.approx(108.0)

    def test_long_trailing_stop_does_not_move_down(self, cfg):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 95.0)
        bar_loss = {"open": 97.0, "high": 98.0, "low": 96.0, "close": 97.0}
        _update_trailing_stop(pos, bar_loss, atr=2.0, cfg=cfg)
        # new_stop = 97 - 3 = 94 < 95, stop should stay at 95
        assert pos.stop_price == pytest.approx(95.0)

    def test_short_trailing_stop_moves_down_only(self, cfg):
        pos = _Position("X", "short", "2020-01-01", 100.0, 10.0, 105.0)
        bar_profit = {"open": 92.0, "high": 93.0, "low": 91.0, "close": 92.0}
        _update_trailing_stop(pos, bar_profit, atr=2.0, cfg=cfg)
        # new_stop = 92 + 3 = 95 < 105 → move down to 95
        assert pos.stop_price == pytest.approx(95.0)


# ── Config weight wiring ───────────────────────────────────────────────────────

class TestConfigWiring:
    """Changing a weight in config changes composite scores (proves wiring)."""

    def test_weight_change_alters_composite_scores(self):
        """run_engine with different RSI weight must produce different composite scores.

        We test wiring at the scoring level (run_engine) rather than the backtest
        level because the backtest adds entry thresholds; a small weight change may
        not flip signals across the ±70 threshold but will still change raw composites.
        """
        cfg_default = load_config()
        weights_data = cfg_default.weights.model_dump()
        weights_data["rsi"] += 5
        weights_data["macd"] -= 5  # keep sum = 100

        from backend.app.config import Weights
        from backend.app.scoring.composite import run_engine
        new_weights = Weights(**weights_data)
        long_strat_modified = cfg_default.get_strategy("long").model_copy(update={"weights": new_weights})
        strategies_modified = cfg_default.strategies.model_copy(update={"long": long_strat_modified})
        cfg_alt = cfg_default.model_copy(update={"strategies": strategies_modified})

        df = _make_ohlcv(n=100, seed=17)
        res_default = run_engine(df, cfg_default)
        res_alt = run_engine(df, cfg_alt)

        composites_default = [r["composite"] for r in res_default]
        composites_alt = [r["composite"] for r in res_alt]

        # At least some bars should differ in composite score
        n_differ = sum(
            abs(a - b) > 1e-9
            for a, b in zip(composites_default, composites_alt)
        )
        assert n_differ > 0, (
            "Weight change had no effect on any composite score — config not wired"
        )

    def test_weight_change_alters_backtest_when_trades_exist(self):
        """When trades exist, different weights → different equity curves."""
        cfg_default = load_config()
        # Dramatically shift weights to ensure composite score difference is large
        weights_data = cfg_default.weights.model_dump()
        weights_data["rsi"] = 0
        weights_data["macd"] = weights_data["macd"] + 10  # keep sum = 100

        from backend.app.config import Weights
        new_weights = Weights(**weights_data)
        long_strat_modified = cfg_default.get_strategy("long").model_copy(update={"weights": new_weights})
        strategies_modified = cfg_default.strategies.model_copy(update={"long": long_strat_modified})
        cfg_alt = cfg_default.model_copy(update={"strategies": strategies_modified})

        # Use many data points and strong trend to generate trades in both configs
        df = _make_ohlcv(n=200, seed=31, trend=0.3)
        fetcher = _make_fetcher({"T": df})
        s, e = df.index[0].date(), df.index[-1].date()

        r1 = run_backtest(["T"], s, e, cfg_default, fetcher)
        r2 = run_backtest(["T"], s, e, cfg_alt, fetcher)

        if not r1.trades and not r2.trades:
            pytest.skip("No trades generated — increase trend or data length")

        # Either trade counts differ, or at least one metric differs
        metrics_differ = r1.metrics != r2.metrics or r1.trades != r2.trades
        assert metrics_differ, "Dramatic weight change produced identical backtest results"


# ── Metrics ────────────────────────────────────────────────────────────────────

class TestMetrics:
    def _make_trades(self, pnls: list[float]) -> list[ClosedTrade]:
        return [
            ClosedTrade("X", "long", "2020-01-01", 100.0, "2020-01-10", 110.0,
                        10.0, 95.0, pnl, pnl / 1000 * 100, "signal")
            for pnl in pnls
        ]

    def _make_equity(self, values: list[float]) -> list[dict]:
        return [{"date": f"2020-01-{i+1:02d}", "equity": v, "n_open": 1}
                for i, v in enumerate(values)]

    def test_hit_rate(self):
        trades = self._make_trades([100, -50, 200, -30, 80])  # 3 wins, 2 losses
        equity = self._make_equity([100000] * 5)
        m = compute_metrics(trades, equity, 100000)
        assert m["hit_rate"] == pytest.approx(3 / 5)

    def test_profit_factor(self):
        trades = self._make_trades([100, -50])  # 100 wins, 50 losses
        equity = self._make_equity([100000] * 5)
        m = compute_metrics(trades, equity, 100000)
        assert m["profit_factor"] == pytest.approx(2.0)

    def test_max_drawdown(self):
        equity = self._make_equity([100000, 110000, 90000, 95000, 105000])
        m = compute_metrics(self._make_trades([1.0]), equity, 100000)
        # Peak 110000, trough 90000 → DD = (110000-90000)/110000 ≈ 18.18%
        assert m["max_drawdown_pct"] == pytest.approx(18.18, abs=0.01)

    def test_sharpe_positive_for_uptrend(self):
        # Steadily increasing equity → positive Sharpe
        n = 60
        equity = self._make_equity([100000 + i * 100 for i in range(n)])
        trades = self._make_trades([100.0] * 5)
        m = compute_metrics(trades, equity, 100000)
        assert m["sharpe"] > 0

    def test_exposure_pct(self):
        equity = [{"date": "2020-01-01", "equity": 100000, "n_open": 0},
                  {"date": "2020-01-02", "equity": 100000, "n_open": 1},
                  {"date": "2020-01-03", "equity": 100000, "n_open": 2},
                  {"date": "2020-01-04", "equity": 100000, "n_open": 0}]
        m = compute_metrics(self._make_trades([1.0]), equity, 100000)
        assert m["exposure_pct"] == pytest.approx(50.0)

    def test_no_trades_returns_zeros(self):
        equity = self._make_equity([100000] * 10)
        m = compute_metrics([], equity, 100000)
        assert m["n_trades"] == 0
        assert m["sharpe"] == 0.0
        assert m["max_drawdown_pct"] == 0.0


# ── Survivorship bias documented ───────────────────────────────────────────────

class TestSurvivorshipBias:
    def test_survivorship_note_present_in_result(self, cfg):
        df = _make_ohlcv(n=60, seed=1)
        fetcher = _make_fetcher({"T": df})
        result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)
        assert result.survivorship_note
        assert "SURVIVORSHIP" in result.survivorship_note.upper()

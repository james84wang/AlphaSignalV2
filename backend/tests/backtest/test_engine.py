"""Backtest engine tests (long-only).

1. No look-ahead: signal(T) is identical whether bars > T exist or not.
2. Entry fills on T+1 open, never T close.
3. Stop uses intrabar high/low correctly.
4. Trailing stop moves up only.
5. Metrics + survivorship note.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.backtest.engine import (
    ClosedTrade,
    _check_stop,
    _Position,
    _update_trailing_stop,
    run_backtest,
)
from backend.app.backtest.metrics import compute_metrics
from backend.app.scoring.confluence import run_engine


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _make_ohlcv(n: int = 120, seed: int = 42, start: str = "2020-01-02", trend: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 + trend * np.arange(n) + np.cumsum(rng.standard_normal(n) * 0.8)
    opens = closes + rng.uniform(-0.5, 0.5, n)
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 1.0, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 1.0, n)
    vols = rng.integers(1_000_000, 10_000_000, n).astype("int64")
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx)


def _make_fetcher(sym_to_df: dict):
    def _fetch(sym: str, start: date, end: date) -> pd.DataFrame:
        if sym not in sym_to_df:
            raise ValueError(f"Unknown symbol: {sym}")
        df = sym_to_df[sym]
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df.index >= s) & (df.index <= e)]
    return _fetch


# ── Anti-look-ahead ────────────────────────────────────────────────────────────

class TestNoLookahead:
    def test_signal_identical_with_future_bars_removed(self, cfg):
        df_full = _make_ohlcv(300, seed=3, trend=0.15)
        df_trunc = df_full.iloc[:250]
        results_full = run_engine(df_full, cfg)
        results_trunc = run_engine(df_trunc, cfg)
        trunc_last_date = str(df_trunc.index[-1].date())
        full_at_trunc = next(r for r in results_full if r["date"] == trunc_last_date)
        trunc_last = results_trunc[-1]
        assert abs(full_at_trunc["composite"] - trunc_last["composite"]) < 1e-9
        assert full_at_trunc["signal"] == trunc_last["signal"]

    def test_multiple_truncation_points(self, cfg):
        df_full = _make_ohlcv(n=320, seed=7, trend=0.1)
        results_full = run_engine(df_full, cfg)
        for cutoff in [220, 250, 280, 300]:
            df_trunc = df_full.iloc[:cutoff]
            results_trunc = run_engine(df_trunc, cfg)
            trunc_date = str(df_trunc.index[-1].date())
            full_bar = next(r for r in results_full if r["date"] == trunc_date)
            trunc_bar = results_trunc[-1]
            assert abs(full_bar["composite"] - trunc_bar["composite"]) < 1e-9
            assert full_bar["signal"] == trunc_bar["signal"]


# ── Entry fills on T+1 open ────────────────────────────────────────────────────

class TestEntryOnNextOpen:
    def _run_with_forced_signal(self, cfg, signal_bar_idx: int = 60):
        df = _make_ohlcv(n=120, seed=55)

        def _fake_compute_signals(data, _cfg, strategy="long"):
            out = []
            for i in range(len(data)):
                if i == signal_bar_idx:
                    out.append({"date": str(data.index[i].date()), "composite": 90.0, "signal": "Strong Buy"})
                else:
                    out.append({"date": str(data.index[i].date()), "composite": 0.0, "signal": "Hold"})
            return out

        fetcher = _make_fetcher({"T": df})
        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake_compute_signals):
            result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)
        return df, result

    def test_entry_date_is_one_bar_after_signal(self, cfg):
        df, result = self._run_with_forced_signal(cfg, 60)
        assert result.trades
        expected_entry_date = str(df.index[61].date())
        assert result.trades[0].entry_date == expected_entry_date

    def test_entry_price_equals_next_open_with_slippage(self, cfg):
        df, result = self._run_with_forced_signal(cfg, 60)
        assert result.trades
        fill_bar_open = float(df.iloc[61]["open"])
        expected = fill_bar_open * (1 + cfg.backtest.slippage_pct)
        assert abs(result.trades[0].entry_price - expected) < 1e-6


# ── Stop intrabar (long) ───────────────────────────────────────────────────────

class TestStopIntrabar:
    def test_long_stop_triggers_at_stop_price_not_open(self):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 98.0)
        bar = {"open": 99.5, "high": 100.5, "low": 97.5, "close": 99.0}
        hit, fill = _check_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(98.0)

    def test_long_stop_not_triggered_when_low_above_stop(self):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 95.0)
        bar = {"open": 99.5, "high": 100.5, "low": 96.0, "close": 99.0}
        hit, _ = _check_stop(pos, bar)
        assert hit is False

    def test_long_stop_gap_down_fills_at_open(self):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 98.0)
        bar = {"open": 96.0, "high": 97.0, "low": 95.0, "close": 96.5}
        hit, fill = _check_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(96.0)

    def test_stop_not_checked_on_entry_bar(self, cfg):
        df = _make_ohlcv(n=200, seed=99, trend=0.4)
        fetcher = _make_fetcher({"T": df})
        result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)
        for trade in result.trades:
            entry = pd.Timestamp(trade.entry_date)
            exit_ = pd.Timestamp(trade.exit_date)
            assert exit_ >= entry
            if trade.exit_reason == "stop":
                assert exit_ > entry


# ── Trailing stop (long) ───────────────────────────────────────────────────────

class TestTrailingStop:
    def test_long_trailing_stop_moves_up_only(self, cfg):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 95.0)
        bar_profit = {"open": 110.0, "high": 112.0, "low": 109.0, "close": 111.0}
        _update_trailing_stop(pos, bar_profit, atr=2.0, cfg=cfg)
        assert pos.stop_price == pytest.approx(108.0)  # 111 - 1.5*2

    def test_long_trailing_stop_does_not_move_down(self, cfg):
        pos = _Position("X", "long", "2020-01-01", 100.0, 10.0, 95.0)
        bar_loss = {"open": 97.0, "high": 98.0, "low": 96.0, "close": 97.0}
        _update_trailing_stop(pos, bar_loss, atr=2.0, cfg=cfg)
        assert pos.stop_price == pytest.approx(95.0)


# ── Metrics ────────────────────────────────────────────────────────────────────

class TestMetrics:
    def _make_trades(self, pnls: list[float]) -> list[ClosedTrade]:
        return [
            ClosedTrade("X", "long", "2020-01-01", 100.0, "2020-01-10", 110.0,
                        10.0, 95.0, pnl, pnl / 1000 * 100, "signal")
            for pnl in pnls
        ]

    def _make_equity(self, values: list[float]) -> list[dict]:
        return [{"date": f"2020-01-{i+1:02d}", "equity": v, "n_open": 1} for i, v in enumerate(values)]

    def test_hit_rate(self):
        m = compute_metrics(self._make_trades([100, -50, 200, -30, 80]), self._make_equity([100000] * 5), 100000)
        assert m["hit_rate"] == pytest.approx(3 / 5)

    def test_profit_factor(self):
        m = compute_metrics(self._make_trades([100, -50]), self._make_equity([100000] * 5), 100000)
        assert m["profit_factor"] == pytest.approx(2.0)

    def test_max_drawdown(self):
        equity = self._make_equity([100000, 110000, 90000, 95000, 105000])
        m = compute_metrics(self._make_trades([1.0]), equity, 100000)
        assert m["max_drawdown_pct"] == pytest.approx(18.18, abs=0.01)

    def test_no_trades_returns_zeros(self):
        m = compute_metrics([], self._make_equity([100000] * 10), 100000)
        assert m["n_trades"] == 0
        assert m["sharpe"] == 0.0
        assert m["max_drawdown_pct"] == 0.0


# ── Survivorship note ───────────────────────────────────────────────────────────

def test_survivorship_note_present(cfg):
    df = _make_ohlcv(n=80, seed=1)
    fetcher = _make_fetcher({"T": df})
    result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)
    assert "SURVIVORSHIP" in result.survivorship_note.upper()


def test_all_trades_are_long(cfg):
    df = _make_ohlcv(n=300, seed=12, trend=0.2)
    fetcher = _make_fetcher({"T": df})
    result = run_backtest(["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher)
    assert all(t.side == "long" for t in result.trades)

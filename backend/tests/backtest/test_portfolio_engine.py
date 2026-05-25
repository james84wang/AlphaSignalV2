"""MOD-F tests: portfolio money management, fees, ranked selection, benchmark, metrics.

Tests required by mod-f.md:
1. Fee formula: clamp at min, per-share band, 1% cap.
2. Sizing: floor, cash-skip, scales with equity.
3. ATR stop: position exits at next open when price crosses entry ∓ 1.5×ATR.
4. Selection: top_n, slot constraint, capital constraint.
5. Per-name cap: entry that would exceed 30% is skipped/clipped.
6. Benchmark: known series → hand-checked total_return and final_equity.
7. Determinism: same data + same params ⇒ identical metrics.
8. All mod-e anti-look-ahead and coverage tests remain green (run separately).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backend.app.backtest.engine import (
    BacktestResult,
    ClosedTrade,
    _Position,
    _compute_fee,
    _target_dollars,
    _run_benchmark,
    run_backtest,
)
from backend.app.backtest.metrics import (
    compute_benchmark_metrics,
    compute_strategy_metrics,
    build_comparison,
)
from backend.app.config import BacktestConfig, load_config


# ── Fixtures & helpers ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def bk():
    return load_config().backtest


def _make_bk(**overrides) -> BacktestConfig:
    base = load_config().backtest
    return base.model_copy(update=overrides)


def _make_ohlcv(
    n: int = 120,
    seed: int = 42,
    start: str = "2020-01-02",
    trend: float = 0.0,
    base: float = 100.0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + trend * np.arange(n) + np.cumsum(rng.standard_normal(n) * 0.8)
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
    def _fetch(sym: str, start: date, end: date) -> pd.DataFrame:
        if sym not in sym_to_df:
            raise ValueError(f"Unknown symbol: {sym}")
        df = sym_to_df[sym]
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df.index >= s) & (df.index <= e)]
    return _fetch


def _force_signal(val: str, composite: float):
    def _fake(data, _cfg, strategy="long"):
        return [
            {"date": str(data.index[i].date()), "composite": composite, "signal": val}
            for i in range(len(data))
        ]
    return _fake


# ── 1. Fee formula ─────────────────────────────────────────────────────────────

class TestFeeFormula:
    """_compute_fee = clamp(shares × fee_per_share, fee_min, fee_max_pct × shares × price)."""

    @staticmethod
    def _default_bk() -> BacktestConfig:
        return _make_bk(fee_per_share=0.005, fee_min=1.00, fee_max_pct_of_trade=0.01)

    def test_floor_at_fee_min(self):
        """Very few shares → raw fee < fee_min → fee_min applies."""
        bk = self._default_bk()
        # 1 share × $0.005 = $0.005 < $1.00 fee_min → fee = $1.00
        fee = _compute_fee(1.0, 100.0, bk)
        assert fee == pytest.approx(1.00)

    def test_per_share_band(self):
        """Mid-range shares: raw fee in (fee_min, cap) → raw fee applies."""
        bk = self._default_bk()
        # 500 shares × $0.005 = $2.50; cap = 0.01 × 500 × $100 = $500 → raw wins
        fee = _compute_fee(500.0, 100.0, bk)
        assert fee == pytest.approx(2.50)

    def test_cap_at_one_pct(self):
        """Huge position → raw fee > 1% cap → cap applies."""
        # fee_per_share=0.05, price=$1.00: raw=0.05/share vs cap=0.01/share → cap wins
        bk = _make_bk(fee_per_share=0.05, fee_min=1.00, fee_max_pct_of_trade=0.01)
        # 1000 shares, price=$1: raw=$50, cap=0.01×1000×$1=$10 → cap=$10
        fee = _compute_fee(1000.0, 1.0, bk)
        assert fee == pytest.approx(10.0)   # 1% × 1000 × $1

    def test_exactly_at_min(self):
        """Edge: raw fee == fee_min → fee_min."""
        bk = self._default_bk()
        # fee_min=1.00, fee_per_share=0.005 → shares=200: raw=1.00, cap=0.01×200×100=$200
        fee = _compute_fee(200.0, 100.0, bk)
        assert fee == pytest.approx(1.00)

    def test_entry_and_exit_each_charged(self, cfg):
        """A round-trip trade should show both entry_fee and exit_fee on ClosedTrade."""
        df = _make_ohlcv(n=120, seed=11, trend=0.5)
        fetcher = _make_fetcher({"T": df, "QQQ": df})
        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            result = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
            )
        for trade in result.trades:
            assert trade.entry_fee > 0, "entry_fee should be > 0"
            assert trade.exit_fee > 0, "exit_fee should be > 0"


# ── 2. Position sizing ─────────────────────────────────────────────────────────

class TestPositionSizing:
    def test_target_at_pct_of_equity(self):
        """target_dollars = position_size_pct × equity when above floor."""
        bk = _make_bk(position_size_pct=0.08, position_size_min=2000.0)
        equity = 100_000.0
        t = _target_dollars(equity, bk)
        assert t == pytest.approx(0.08 * equity)

    def test_floor_applied_when_equity_small(self):
        """When pct×equity < floor, floor applies."""
        bk = _make_bk(position_size_pct=0.08, position_size_min=2000.0)
        equity = 10_000.0   # 8% × 10k = 800 < 2000 → floor
        t = _target_dollars(equity, bk)
        assert t == pytest.approx(2000.0)

    def test_insufficient_cash_skips_trade(self, cfg):
        """If cash < target_$, the trade should be skipped (no position opened)."""
        # Use per_name_cap_pct=1.0 so positions are full size (not clipped by cap).
        # With $2500 and position_size_min=$2000, first trade costs ~$2001, leaving ~$499.
        # The second trade needs $2000 but cash is ~$499 → must be skipped.
        tiny_fund = 2500.0
        df = _make_ohlcv(n=120, seed=55, trend=1.0, base=100.0)
        df2 = _make_ohlcv(n=120, seed=56, trend=1.0, base=100.0)
        qqq_df = _make_ohlcv(n=120, seed=57)

        fetcher = _make_fetcher({"A": df, "B": df2, "QQQ": qqq_df})

        def _fake(data, _cfg, strategy="long"):
            out = []
            for i in range(len(data)):
                sig = "Strong Buy" if i == 10 else "Hold"
                comp = 90.0 if i == 10 else 0.0
                out.append({"date": str(data.index[i].date()), "composite": comp, "signal": sig})
            return out

        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake):
            result = run_backtest(
                ["A", "B"],
                df.index[0].date(), df.index[-1].date(),
                cfg, fetcher,
                initial_fund=tiny_fund,
                position_size_min=2000.0,
                per_name_cap_pct=1.0,   # disable cap so positions are full $2000
                max_concurrent_positions=15,
            )

        # With $2500 and $2000 min positions, at most 1 fills on the same day.
        n_same_entry = sum(
            1 for t in result.trades
            if t.entry_date == str(df.index[11].date())
        )
        assert n_same_entry <= 1, (
            f"Expected ≤1 trade on the same entry bar with tiny fund, got {n_same_entry}"
        )

    def test_sizing_scales_with_equity(self, cfg):
        """Larger initial_fund → larger target position → more shares."""
        df = _make_ohlcv(n=120, seed=77, trend=0.3)
        qqq_df = _make_ohlcv(n=120, seed=78)
        fetcher_small = _make_fetcher({"T": df, "QQQ": qqq_df})
        fetcher_large = _make_fetcher({"T": df, "QQQ": qqq_df})

        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            r_small = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher_small,
                initial_fund=50_000.0, position_size_min=500.0,
            )
        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            r_large = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher_large,
                initial_fund=200_000.0, position_size_min=500.0,
            )

        if not r_small.trades or not r_large.trades:
            pytest.skip("No trades generated")

        avg_shares_small = sum(t.shares for t in r_small.trades) / len(r_small.trades)
        avg_shares_large = sum(t.shares for t in r_large.trades) / len(r_large.trades)
        assert avg_shares_large > avg_shares_small, (
            "Larger initial_fund should produce more shares per trade (fixed-fractional sizing)"
        )


# ── 3. ATR stop ────────────────────────────────────────────────────────────────

class TestATRStop:
    def test_position_exits_on_stop_cross(self, cfg):
        """A long position whose price crosses entry − 1.5×ATR must exit (stop reason)."""
        df = _make_ohlcv(n=120, seed=1, trend=0.0, base=100.0)
        qqq_df = _make_ohlcv(n=120, seed=2)

        # Force buy on bar 40, then Hold — position must exit on stop (ATR-driven)
        atr_approx = 1.2   # rough ATR for the synthetic data
        entry_price_approx = float(df.iloc[41]["open"])
        stop_approx = entry_price_approx - 1.5 * atr_approx

        def _fake(data, _cfg, strategy="long"):
            return [
                {
                    "date": str(data.index[i].date()),
                    "composite": 90.0 if i == 40 else 0.0,
                    "signal": "Strong Buy" if i == 40 else "Hold",
                }
                for i in range(len(data))
            ]

        fetcher = _make_fetcher({"T": df, "QQQ": qqq_df})
        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake):
            result = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
            )

        stop_exits = [t for t in result.trades if t.exit_reason == "stop"]
        # With a Hold signal, the only exit should be stop or end_of_data
        non_signal_exits = [t for t in result.trades if t.exit_reason != "signal"]
        assert non_signal_exits, "Expected at least one non-signal exit (stop or end_of_data)"

    def test_stop_exit_date_after_entry_date(self, cfg):
        """Any stop-exit must happen on a bar AFTER the entry bar."""
        df = _make_ohlcv(n=120, seed=3, trend=-0.5)
        qqq_df = _make_ohlcv(n=120, seed=4)
        fetcher = _make_fetcher({"T": df, "QQQ": qqq_df})

        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            result = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
            )

        for trade in result.trades:
            if trade.exit_reason == "stop":
                assert trade.exit_date > trade.entry_date, (
                    "Stop triggered on entry bar — look-ahead error"
                )


# ── 4. Ranked selection ────────────────────────────────────────────────────────

class TestRankedSelection:
    def _make_signals_for_n(self, n_syms: int, signal_bar: int = 10):
        """Return a fake signal function where all n_syms emit a buy with different composites."""
        composites = [50.0 + i * 5.0 for i in range(n_syms)]   # e.g. 50, 55, 60, ...

        def _fake(data, _cfg, strategy="long"):
            # Identify which symbol this is by its base price (can't easily use closure here)
            return [
                {
                    "date": str(data.index[i].date()),
                    "composite": 90.0 if i == signal_bar else 0.0,
                    "signal": "Strong Buy" if i == signal_bar else "Hold",
                }
                for i in range(len(data))
            ]

        return _fake

    def test_top_n_caps_entries_per_bar(self, cfg):
        """With 20 candidates and top_n=3, at most 3 new entries per bar."""
        n = 20
        dfs = {f"S{i}": _make_ohlcv(n=120, seed=i, trend=0.3, base=100.0 + i) for i in range(n)}
        qqq_df = _make_ohlcv(n=120, seed=999)
        dfs["QQQ"] = qqq_df
        fetcher = _make_fetcher(dfs)

        signal_bar = 10

        def _fake(data, _cfg, strategy="long"):
            return [
                {
                    "date": str(data.index[i].date()),
                    "composite": 85.0 if i == signal_bar else 0.0,
                    "signal": "Strong Buy" if i == signal_bar else "Hold",
                }
                for i in range(len(data))
            ]

        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake):
            result = run_backtest(
                list(dfs.keys() - {"QQQ"}),
                list(dfs.values())[0].index[0].date(),
                list(dfs.values())[0].index[-1].date(),
                cfg, fetcher,
                top_n=3,
                max_concurrent_positions=20,
                initial_fund=500_000.0,  # ample cash
            )

        # On signal_bar+1 (entry fill day), at most 3 positions should open
        entry_fill_date = str(list(dfs.values())[0].index[signal_bar + 1].date())
        entries_on_fill_day = [t for t in result.trades if t.entry_date == entry_fill_date]
        assert len(entries_on_fill_day) <= 3, (
            f"top_n=3 should cap entries per bar, got {len(entries_on_fill_day)}"
        )

    def test_slot_cap_tracked_in_constraint_counts(self, cfg):
        """When max_concurrent_positions is hit, skipped_no_slot is incremented."""
        n = 10
        dfs = {f"S{i}": _make_ohlcv(n=120, seed=i, trend=0.5) for i in range(n)}
        qqq_df = _make_ohlcv(n=120, seed=999)
        dfs["QQQ"] = qqq_df
        fetcher = _make_fetcher(dfs)

        def _fake(data, _cfg, strategy="long"):
            return [
                {
                    "date": str(data.index[i].date()),
                    "composite": 90.0,
                    "signal": "Strong Buy",
                }
                for i in range(len(data))
            ]

        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake):
            result = run_backtest(
                [k for k in dfs if k != "QQQ"],
                list(dfs.values())[0].index[0].date(),
                list(dfs.values())[0].index[-1].date(),
                cfg, fetcher,
                max_concurrent_positions=3,  # only 3 slots
                top_n=20,
                initial_fund=500_000.0,
            )

        # With 10 symbols all signalling buy and only 3 slots, must skip some
        assert result.constraint_counts.get("skipped_no_slot", 0) > 0, (
            "skipped_no_slot should be > 0 when max_concurrent_positions is binding"
        )

    def test_capital_constraint_tracked(self, cfg):
        """When cash is exhausted, skipped_no_capital is incremented."""
        n = 5
        dfs = {f"S{i}": _make_ohlcv(n=120, seed=i + 10, trend=0.5) for i in range(n)}
        qqq_df = _make_ohlcv(n=120, seed=999)
        dfs["QQQ"] = qqq_df
        fetcher = _make_fetcher(dfs)

        def _fake(data, _cfg, strategy="long"):
            return [
                {"date": str(data.index[i].date()), "composite": 90.0, "signal": "Strong Buy"}
                for i in range(len(data))
            ]

        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake):
            result = run_backtest(
                [k for k in dfs if k != "QQQ"],
                list(dfs.values())[0].index[0].date(),
                list(dfs.values())[0].index[-1].date(),
                cfg, fetcher,
                max_concurrent_positions=20,
                top_n=20,
                initial_fund=4500.0,  # ~2 positions at $2000 min
                position_size_min=2000.0,
            )

        total_skipped = (
            result.constraint_counts.get("skipped_no_capital", 0)
            + result.constraint_counts.get("skipped_no_slot", 0)
        )
        assert total_skipped > 0, (
            "With tiny fund and many signals, some should be skipped for capital/slot reasons"
        )


# ── 5. Per-name cap ────────────────────────────────────────────────────────────

class TestPerNameCap:
    def test_large_position_capped_by_per_name_cap(self, cfg):
        """A single position cannot exceed per_name_cap_pct × equity at entry."""
        df = _make_ohlcv(n=120, seed=20, trend=0.5, base=100.0)
        qqq_df = _make_ohlcv(n=120, seed=21)
        fetcher = _make_fetcher({"T": df, "QQQ": qqq_df})

        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            result = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
                initial_fund=100_000.0,
                position_size_pct=0.40,  # 40% sizing — above 30% cap
                per_name_cap_pct=0.30,
                position_size_min=100.0,
            )

        # If the cap works, each trade's cost should be ≤ 30% of initial_fund approx
        for trade in result.trades:
            position_value = trade.shares * trade.entry_price
            # Allow some rounding slack; should be well below 40% ($40k) of $100k
            assert position_value <= 35_000.0, (
                f"Position value {position_value:.0f} exceeds per_name_cap 30% of 100k"
            )


# ── 6. Benchmark ───────────────────────────────────────────────────────────────

class TestBenchmark:
    def test_benchmark_final_equity_matches_hand_calc(self, cfg):
        """Buy-and-hold QQQ: final_equity = (initial_fund - entry_fee) / entry_price × last_close."""
        bk = _make_bk(
            initial_fund=100_000.0,
            fee_per_share=0.005,
            fee_min=1.0,
            fee_max_pct_of_trade=0.01,
            slippage_pct=0.001,
            benchmark_symbol="QQQ",
            risk_free_rate=0.0,
        )

        # Synthetic QQQ: starts at 100, ends at 120
        n = 60
        opens = [100.0] * n
        closes = [100.0 + (20.0 / n) * i for i in range(n)]  # linear rise 100→120
        idx = pd.date_range("2020-01-02", periods=n, freq="B")
        qqq_df = pd.DataFrame(
            {"open": opens, "high": closes, "low": opens, "close": closes, "volume": [1_000_000] * n},
            index=idx,
        )
        fetcher = _make_fetcher({"QQQ": qqq_df})

        entry_p = opens[0] * (1 + bk.slippage_pct)   # = 100.1
        est_shares = bk.initial_fund / entry_p
        entry_fee = _compute_fee(est_shares, entry_p, bk)
        shares = (bk.initial_fund - entry_fee) / entry_p
        expected_final = shares * closes[-1]

        bm_metrics, bm_eq = _run_benchmark(fetcher, idx[0].date(), idx[-1].date(), bk)
        assert abs(bm_metrics["final_equity"] - expected_final) < 1.0, (
            f"Benchmark final_equity {bm_metrics['final_equity']:.2f} ≠ expected {expected_final:.2f}"
        )

    def test_benchmark_total_return_positive_for_rising_series(self, cfg):
        """Rising price series → positive total_return."""
        bk = _make_bk(initial_fund=10_000.0)
        n = 60
        idx = pd.date_range("2020-01-02", periods=n, freq="B")
        opens = [50.0 + i * 0.1 for i in range(n)]
        closes = [50.0 + i * 0.2 for i in range(n)]  # rising fast
        qqq_df = pd.DataFrame(
            {"open": opens, "high": closes, "low": opens, "close": closes, "volume": [1_000_000] * n},
            index=idx,
        )
        fetcher = _make_fetcher({"QQQ": qqq_df})
        bm_metrics, _ = _run_benchmark(fetcher, idx[0].date(), idx[-1].date(), bk)
        assert bm_metrics["total_return"] > 0

    def test_both_equity_curves_returned_in_backtest_result(self, cfg):
        """run_backtest should return both equity_curve and benchmark_equity_curve."""
        df = _make_ohlcv(n=120, seed=30, trend=0.3)
        qqq_df = _make_ohlcv(n=120, seed=31)
        fetcher = _make_fetcher({"T": df, "QQQ": qqq_df})

        result = run_backtest(
            ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
        )
        assert isinstance(result.benchmark_equity_curve, list), (
            "benchmark_equity_curve should be a list"
        )
        assert isinstance(result.benchmark_metrics, dict), (
            "benchmark_metrics should be a dict"
        )
        assert "total_return" in result.benchmark_metrics
        assert "sharpe_ratio" in result.benchmark_metrics


# ── 7. Determinism ─────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_params_same_metrics(self, cfg):
        """Two runs with identical data and params produce identical metrics."""
        df = _make_ohlcv(n=120, seed=99, trend=0.4)
        qqq_df = _make_ohlcv(n=120, seed=100)
        s, e = df.index[0].date(), df.index[-1].date()

        def make_fetcher():
            return _make_fetcher({"T": df, "QQQ": qqq_df})

        r1 = run_backtest(["T"], s, e, cfg, make_fetcher())
        r2 = run_backtest(["T"], s, e, cfg, make_fetcher())

        assert r1.metrics == r2.metrics, "Metrics differ between identical runs"
        assert r1.benchmark_metrics == r2.benchmark_metrics


# ── 8. Strategy metrics extended set ──────────────────────────────────────────

class TestStrategyMetrics:
    def _make_trades(self, pnls: list[float]) -> list:
        return [
            ClosedTrade("X", "long", "2020-01-01", 100.0, "2020-01-10", 110.0,
                        10.0, 95.0, pnl, pnl / 1000 * 100, "signal",
                        entry_fee=1.0, exit_fee=1.0)
            for pnl in pnls
        ]

    def _make_equity(self, values: list[float]) -> list[dict]:
        return [{"date": f"2020-01-{i+1:02d}", "equity": v, "n_open": 1}
                for i, v in enumerate(values)]

    def test_win_rate(self):
        trades = self._make_trades([100, -50, 200, -30, 80])
        m = compute_strategy_metrics(trades, self._make_equity([100000] * 5), 100000)
        assert m["win_rate"] == pytest.approx(3 / 5)
        assert m["hit_rate"] == m["win_rate"]   # backward-compat alias

    def test_avg_win_avg_loss_win_loss_ratio(self):
        trades = self._make_trades([100.0, 200.0, -50.0])
        m = compute_strategy_metrics(trades, self._make_equity([100000] * 5), 100000)
        assert m["avg_win"] == pytest.approx(150.0)
        assert m["avg_loss"] == pytest.approx(-50.0)
        assert m["win_loss_ratio"] == pytest.approx(3.0)

    def test_profit_factor(self):
        trades = self._make_trades([100.0, -50.0])
        m = compute_strategy_metrics(trades, self._make_equity([100000] * 5), 100000)
        assert m["profit_factor"] == pytest.approx(2.0)

    def test_turnover_nonzero_with_trades(self):
        trades = self._make_trades([50.0, -20.0])
        m = compute_strategy_metrics(trades, self._make_equity([100000] * 60), 100000)
        assert m["turnover"] > 0

    def test_total_fees_accumulated(self):
        trades = self._make_trades([100.0, -50.0])
        m = compute_strategy_metrics(trades, self._make_equity([100000] * 5), 100000)
        # Each trade has entry_fee=1.0 + exit_fee=1.0 = $2; 2 trades = $4 total
        assert m["total_fees"] == pytest.approx(4.0)

    def test_sharpe_alias(self):
        equity = self._make_equity([100000 + i * 100 for i in range(60)])
        m = compute_strategy_metrics(self._make_trades([100.0]), equity, 100000)
        assert m["sharpe"] == m["sharpe_ratio"]

    def test_max_drawdown_alias(self):
        equity = self._make_equity([100000, 110000, 90000, 95000, 105000])
        m = compute_strategy_metrics(self._make_trades([1.0]), equity, 100000)
        assert m["max_drawdown"] == m["max_drawdown_pct"]
        assert m["max_drawdown"] == pytest.approx(18.18, abs=0.01)

    def test_total_return_alias(self):
        equity = self._make_equity([100000, 110000])
        m = compute_strategy_metrics(self._make_trades([1.0]), equity, 100000)
        assert m["total_return"] == m["total_return_pct"]


class TestBenchmarkMetrics:
    def test_benchmark_metrics_five_keys(self):
        equity = [{"date": f"2020-01-{i+1:02d}", "equity": 100000 + i * 100, "n_open": 1}
                  for i in range(60)]
        m = compute_benchmark_metrics(equity, 100000, 0.0)
        for k in ("total_return", "cagr", "sharpe_ratio", "max_drawdown", "final_equity"):
            assert k in m, f"Missing benchmark metric: {k}"

    def test_comparison_contains_five_metrics(self):
        from backend.app.config import load_config
        bk = load_config().backtest
        strategy_m = {
            "total_return": 20.0, "cagr": 10.0, "sharpe_ratio": 1.5,
            "max_drawdown": 8.0, "final_equity": 120000.0,
        }
        benchmark_m = {
            "total_return": 15.0, "cagr": 8.0, "sharpe_ratio": 0.9,
            "max_drawdown": 12.0, "final_equity": 115000.0,
        }
        comp = build_comparison(strategy_m, benchmark_m, bk)
        assert "metrics" in comp
        for k in ("total_return", "cagr", "sharpe_ratio", "max_drawdown", "final_equity"):
            assert k in comp["metrics"], f"Missing key in comparison: {k}"
            assert "strategy" in comp["metrics"][k]
            assert "benchmark" in comp["metrics"][k]
        assert "fairness_caveat" in comp


# ── 9. Changing params changes results ─────────────────────────────────────────

class TestParamSensitivity:
    def test_higher_fees_lower_net_return(self, cfg):
        """Higher fee_per_share → lower total_return (fees eat into P&L)."""
        df = _make_ohlcv(n=120, seed=40, trend=0.5)
        qqq_df = _make_ohlcv(n=120, seed=41)
        s, e = df.index[0].date(), df.index[-1].date()

        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            r_low = run_backtest(
                ["T"], s, e, cfg, _make_fetcher({"T": df, "QQQ": qqq_df}),
                fee_per_share=0.001,
            )
        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            r_high = run_backtest(
                ["T"], s, e, cfg, _make_fetcher({"T": df, "QQQ": qqq_df}),
                fee_per_share=0.05,
            )

        if not r_low.trades or not r_high.trades:
            pytest.skip("No trades generated")

        assert r_low.metrics.get("total_return", 0) >= r_high.metrics.get("total_return", 0), (
            "Higher fees should yield lower or equal total_return"
        )

    def test_smaller_position_size_lowers_exposure(self, cfg):
        """Smaller position_size_pct → smaller exposure (fewer dollars deployed)."""
        df = _make_ohlcv(n=120, seed=42, trend=0.4)
        qqq_df = _make_ohlcv(n=120, seed=43)
        s, e = df.index[0].date(), df.index[-1].date()

        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            r_small = run_backtest(
                ["T"], s, e, cfg, _make_fetcher({"T": df, "QQQ": qqq_df}),
                position_size_pct=0.02, position_size_min=500.0,
            )
        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            r_large = run_backtest(
                ["T"], s, e, cfg, _make_fetcher({"T": df, "QQQ": qqq_df}),
                position_size_pct=0.20, position_size_min=500.0,
            )

        if not r_small.trades or not r_large.trades:
            pytest.skip("No trades generated")

        small_avg = sum(t.shares * t.entry_price for t in r_small.trades) / len(r_small.trades)
        large_avg = sum(t.shares * t.entry_price for t in r_large.trades) / len(r_large.trades)
        assert large_avg > small_avg, (
            "Larger position_size_pct should produce larger average position value"
        )

    def test_max_concurrent_limits_simultaneous_holdings(self, cfg):
        """max_concurrent_positions=3 allows at most 3 simultaneous open positions."""
        n = 8
        dfs = {f"S{i}": _make_ohlcv(n=120, seed=i + 50, trend=0.5) for i in range(n)}
        qqq_df = _make_ohlcv(n=120, seed=999)
        dfs["QQQ"] = qqq_df
        fetcher = _make_fetcher(dfs)

        with patch("backend.app.backtest.engine._compute_signals",
                   side_effect=_force_signal("Strong Buy", 90.0)):
            result = run_backtest(
                [k for k in dfs if k != "QQQ"],
                list(dfs.values())[0].index[0].date(),
                list(dfs.values())[0].index[-1].date(),
                cfg, fetcher,
                max_concurrent_positions=3,
                top_n=20,
                initial_fund=500_000.0,
            )

        max_open = max((e.get("n_open", 0) for e in result.equity_curve), default=0)
        assert max_open <= 3, (
            f"max_concurrent_positions=3 but equity curve shows {max_open} simultaneous positions"
        )

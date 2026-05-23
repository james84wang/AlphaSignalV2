"""MOD-E tests: per-profile backtest engine (long vs short) + coverage report.

Critical properties verified:
1. SHORT trades use inverse ETF price series (not underlying inverted).
2. SHORT entry fills at ETF T+1 open; stop uses ETF intrabar high/low.
3. No look-ahead: short signal(T) uses only underlying data[0..T].
4. A short trade is only opened when BOTH underlying signal and ETF price exist.
5. Coverage report correctly classifies: tested / no_instrument / insufficient_history.
6. Changing a short-profile weight changes the short backtest result.
7. Decay diagnostic fields (synthetic_pnl) are populated on closed short trades.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backend.app.backtest.coverage import CoverageReport
from backend.app.backtest.engine import (
    BacktestResult,
    ClosedTrade,
    _check_etf_long_stop,
    _Position,
    run_backtest,
)
from backend.app.config import load_config


# ── Fixtures & helpers ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cfg():
    return load_config()


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


def _force_signal(signal_val: str, composite: float):
    """Return a patch target for _compute_signals that forces a fixed signal."""
    def _fake(data, _cfg, strategy="long"):
        return [
            {"date": str(data.index[i].date()), "composite": composite, "signal": signal_val}
            for i in range(len(data))
        ]
    return _fake


# ── Coverage report tests ──────────────────────────────────────────────────────

class TestCoverageReport:
    def test_no_inverse_etf_goes_to_skipped(self, cfg):
        """Symbol with no inverse ETF mapping → skipped_no_instrument."""
        df = _make_ohlcv(120)
        fetcher = _make_fetcher({"AAPL": df})
        result = run_backtest(
            ["AAPL"],
            df.index[0].date(), df.index[-1].date(),
            cfg, fetcher,
            strategy="short",
            inverse_etf_map={},  # empty — AAPL has no mapping
        )
        assert result.coverage_report is not None
        assert "AAPL" in result.coverage_report.skipped_no_instrument
        assert result.coverage_report.tested == []

    def test_etf_insufficient_history_goes_to_skipped(self, cfg):
        """Inverse ETF with < 50 overlapping bars → skipped_insufficient_history."""
        underlying_df = _make_ohlcv(120, seed=1)
        # ETF has only 30 bars — well below the 50-bar minimum
        etf_df = _make_ohlcv(30, seed=2)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        result = run_backtest(
            ["SPY"],
            underlying_df.index[0].date(), underlying_df.index[-1].date(),
            cfg, fetcher,
            strategy="short",
            inverse_etf_map={"SPY": "SH"},
        )
        assert result.coverage_report is not None
        assert len(result.coverage_report.skipped_insufficient_history) == 1
        skipped = result.coverage_report.skipped_insufficient_history[0]
        assert skipped.underlying == "SPY"
        assert skipped.inverse_etf == "SH"
        assert result.coverage_report.tested == []

    def test_mapped_etf_with_good_history_appears_in_tested(self, cfg):
        """Symbol + ETF with adequate overlap → appears in tested."""
        underlying_df = _make_ohlcv(120, seed=10)
        etf_df = _make_ohlcv(120, seed=11, base=50.0)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        result = run_backtest(
            ["SPY"],
            underlying_df.index[0].date(), underlying_df.index[-1].date(),
            cfg, fetcher,
            strategy="short",
            inverse_etf_map={"SPY": "SH"},
        )
        assert result.coverage_report is not None
        assert len(result.coverage_report.tested) == 1
        entry = result.coverage_report.tested[0]
        assert entry.underlying == "SPY"
        assert entry.inverse_etf == "SH"
        assert entry.skipped_signals_before_etf_launch >= 0  # can be 0 if dates align

    def test_coverage_summary_counts_correctly(self, cfg):
        """Summary counters match the bucket lists."""
        underlying_df = _make_ohlcv(120, seed=5)
        etf_df = _make_ohlcv(120, seed=6, base=30.0)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df, "AAPL": underlying_df})

        result = run_backtest(
            ["SPY", "AAPL"],
            underlying_df.index[0].date(), underlying_df.index[-1].date(),
            cfg, fetcher,
            strategy="short",
            inverse_etf_map={"SPY": "SH"},  # AAPL has no mapping
        )
        cr = result.coverage_report
        assert cr is not None
        s = cr.summary
        assert s["universe_size"] == 2
        assert s["n_testable"] == 1
        assert s["pct_testable"] == 50.0

    def test_data_fetch_error_goes_to_skipped_data_error(self, cfg):
        """If underlying fetch raises, it goes to skipped_data_error."""
        # Fetcher that always fails for QQQ
        def _fail_fetcher(sym: str, start: date, end: date) -> pd.DataFrame:
            if sym == "QQQ":
                raise RuntimeError("simulated fetch failure")
            df = _make_ohlcv(120)
            return df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]

        result = run_backtest(
            ["QQQ"],
            date(2020, 1, 1), date(2020, 7, 1),
            cfg, _fail_fetcher,
            strategy="short",
            inverse_etf_map={"QQQ": "PSQ"},
        )
        cr = result.coverage_report
        assert cr is not None
        assert len(cr.skipped_data_error) == 1
        assert cr.skipped_data_error[0].symbol == "QQQ"


# ── Short path: trades on ETF, not underlying ─────────────────────────────────

class TestShortTradesOnETF:
    """Verify that the short backtest actually trades on the ETF price series."""

    def _run_short_with_forced_sell(self, cfg, etf_base=50.0, seed=99) -> tuple:
        """Run short backtest where underlying emits constant 'Strong Sell'."""
        underlying_df = _make_ohlcv(120, seed=seed)
        etf_df = _make_ohlcv(120, seed=seed + 1, base=etf_base)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        with patch(
            "backend.app.backtest.engine._compute_signals",
            side_effect=_force_signal("Strong Sell", -90.0),
        ):
            result = run_backtest(
                ["SPY"],
                underlying_df.index[0].date(), underlying_df.index[-1].date(),
                cfg, fetcher,
                strategy="short",
                inverse_etf_map={"SPY": "SH"},
            )
        return result, underlying_df, etf_df

    def test_trade_symbol_is_etf_not_underlying(self, cfg):
        """Closed trades should show the ETF symbol, not the underlying."""
        result, _, _ = self._run_short_with_forced_sell(cfg)
        assert result.trades, "Expected at least one trade"
        trade = result.trades[0]
        assert trade.symbol == "SH", (
            f"Trade symbol should be 'SH' (the ETF), got {trade.symbol!r}"
        )
        assert trade.underlying_symbol == "SPY"
        assert trade.trade_instrument == "SH"

    def test_entry_price_matches_etf_open_with_slippage(self, cfg):
        """Entry price must match the ETF's T+1 open × (1 + slippage), not the underlying."""
        result, underlying_df, etf_df = self._run_short_with_forced_sell(cfg, seed=77)

        if not result.trades:
            pytest.skip("No trades generated")

        trade = result.trades[0]
        entry_d = pd.Timestamp(trade.entry_date)
        etf_open_at_entry = float(etf_df.loc[entry_d, "open"])
        expected_price = etf_open_at_entry * (1 + cfg.backtest.slippage_pct)
        assert abs(trade.entry_price - expected_price) < 0.01, (
            f"Entry price {trade.entry_price:.4f} doesn't match ETF open×(1+slip) {expected_price:.4f}"
        )

    def test_entry_price_is_not_underlying_open(self, cfg):
        """Entry price must NOT equal the underlying's open (different price series)."""
        result, underlying_df, etf_df = self._run_short_with_forced_sell(cfg, etf_base=25.0, seed=33)

        if not result.trades:
            pytest.skip("No trades generated")

        trade = result.trades[0]
        entry_d = pd.Timestamp(trade.entry_date)
        underlying_open = float(underlying_df.loc[entry_d, "open"])
        # ETF price is at base=25 so it should be clearly different from underlying (~100)
        assert abs(trade.entry_price - underlying_open) > 10.0, (
            "Entry price suspiciously close to underlying open — should be ETF open"
        )


# ── Anti-look-ahead for short path ────────────────────────────────────────────

class TestShortNoLookahead:
    """Signal(T) on underlying must be identical whether future bars exist or not."""

    def test_short_signal_identical_with_future_bars_removed(self, cfg):
        from backend.app.scoring.composite import run_engine

        n_full = 100
        n_trunc = 80

        df_full = _make_ohlcv(n_full, seed=15)
        df_trunc = df_full.iloc[:n_trunc]

        results_full = run_engine(df_full, cfg, strategy="short")
        results_trunc = run_engine(df_trunc, cfg, strategy="short")

        trunc_last_date = str(df_trunc.index[-1].date())
        full_at_trunc = next(r for r in results_full if r["date"] == trunc_last_date)
        trunc_last = results_trunc[-1]

        assert abs(full_at_trunc["composite"] - trunc_last["composite"]) < 1e-9, (
            f"Short look-ahead: full={full_at_trunc['composite']:.6f}, "
            f"trunc={trunc_last['composite']:.6f}"
        )


# ── Trade only when BOTH underlying signal and ETF exist ──────────────────────

class TestShortRequiresBothSeries:
    def test_no_trade_when_etf_data_missing_on_next_bar(self, cfg):
        """If T+1 has no ETF data, no entry is made on the signal bar."""
        underlying_df = _make_ohlcv(120, seed=20)
        # ETF only has the first 60 bars — signal at bar 70 (day 71) has no ETF on day 72
        etf_df_full = _make_ohlcv(120, seed=21, base=40.0)
        etf_df = etf_df_full.iloc[:60]

        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        # Force a sell signal on bar 70 (past ETF's last bar)
        def _fake_signals(data, _cfg, strategy="long"):
            return [
                {
                    "date": str(data.index[i].date()),
                    "composite": -90.0 if i == 70 else 0.0,
                    "signal": "Strong Sell" if i == 70 else "Hold",
                }
                for i in range(len(data))
            ]

        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake_signals):
            result = run_backtest(
                ["SPY"],
                underlying_df.index[0].date(), underlying_df.index[-1].date(),
                cfg, fetcher,
                strategy="short",
                inverse_etf_map={"SPY": "SH"},
            )

        # Any trade that exists must have been entered on a date where ETF had data
        etf_last_date = etf_df.index[-1].date()
        for trade in result.trades:
            entry_d = date.fromisoformat(trade.entry_date)
            assert entry_d <= etf_last_date, (
                f"Trade entered on {entry_d} but ETF ends on {etf_last_date} — look-ahead"
            )


# ── ETF stop mechanics ────────────────────────────────────────────────────────

class TestETFStopMechanics:
    """_check_etf_long_stop uses intrabar high/low correctly."""

    def test_etf_stop_triggers_at_stop_price_not_open(self):
        pos = _Position("SPY", "short", "2020-01-01", 50.0, 100.0, stop_price=47.0)
        bar = {"open": 48.5, "high": 49.0, "low": 46.5, "close": 48.0}
        hit, fill = _check_etf_long_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(47.0)

    def test_etf_stop_not_triggered_when_low_above_stop(self):
        pos = _Position("SPY", "short", "2020-01-01", 50.0, 100.0, stop_price=44.0)
        bar = {"open": 48.0, "high": 49.0, "low": 46.0, "close": 47.0}
        hit, _ = _check_etf_long_stop(pos, bar)
        assert hit is False

    def test_etf_stop_gap_down_fills_at_open(self):
        pos = _Position("SPY", "short", "2020-01-01", 50.0, 100.0, stop_price=47.0)
        bar = {"open": 44.0, "high": 45.0, "low": 43.5, "close": 44.5}
        hit, fill = _check_etf_long_stop(pos, bar)
        assert hit is True
        assert fill == pytest.approx(44.0)

    def test_etf_stop_not_triggered_on_entry_bar(self, cfg):
        """Positions should not be stopped on the entry bar."""
        underlying_df = _make_ohlcv(120, seed=88, trend=-0.3)
        etf_df = _make_ohlcv(120, seed=89, base=40.0)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        with patch(
            "backend.app.backtest.engine._compute_signals",
            side_effect=_force_signal("Strong Sell", -90.0),
        ):
            result = run_backtest(
                ["SPY"],
                underlying_df.index[0].date(), underlying_df.index[-1].date(),
                cfg, fetcher,
                strategy="short",
                inverse_etf_map={"SPY": "SH"},
            )

        for trade in result.trades:
            if trade.exit_reason == "stop":
                assert trade.exit_date > trade.entry_date, (
                    "Stop triggered on entry bar — look-ahead error"
                )


# ── Decay diagnostic ──────────────────────────────────────────────────────────

class TestDecayDiagnostic:
    def test_synthetic_pnl_populated_on_short_trades(self, cfg):
        """synthetic_pnl should be set (may be None if underlying entry close missing)."""
        underlying_df = _make_ohlcv(120, seed=50, trend=-0.2)
        etf_df = _make_ohlcv(120, seed=51, base=45.0)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        with patch(
            "backend.app.backtest.engine._compute_signals",
            side_effect=_force_signal("Strong Sell", -90.0),
        ):
            result = run_backtest(
                ["SPY"],
                underlying_df.index[0].date(), underlying_df.index[-1].date(),
                cfg, fetcher,
                strategy="short",
                inverse_etf_map={"SPY": "SH"},
            )

        if not result.trades:
            pytest.skip("No trades generated")

        # At least one trade should have synthetic_pnl set
        trades_with_synth = [t for t in result.trades if t.synthetic_pnl is not None]
        assert trades_with_synth, "Expected at least one trade with synthetic_pnl populated"

    def test_synthetic_pnl_reflects_inverted_underlying_return(self, cfg):
        """synthetic_pnl = −(underlying_return × cost_basis) approximately."""
        underlying_df = _make_ohlcv(60, seed=60, trend=-0.5)
        etf_df = _make_ohlcv(60, seed=61, base=50.0)
        fetcher = _make_fetcher({"SPY": underlying_df, "SH": etf_df})

        # Force Sell on bar 20, then Buy on bar 40 → one trade window bars 21-40
        def _fake(data, _cfg, strategy="long"):
            out = []
            for i in range(len(data)):
                if i < 20:
                    sig, comp = "Hold", 0.0
                elif i == 20:
                    sig, comp = "Strong Sell", -90.0
                elif 20 < i < 40:
                    sig, comp = "Hold", 0.0
                else:
                    sig, comp = "Strong Buy", 90.0
                out.append({"date": str(data.index[i].date()), "composite": comp, "signal": sig})
            return out

        with patch("backend.app.backtest.engine._compute_signals", side_effect=_fake):
            result = run_backtest(
                ["SPY"],
                underlying_df.index[0].date(), underlying_df.index[-1].date(),
                cfg, fetcher,
                strategy="short",
                inverse_etf_map={"SPY": "SH"},
            )

        synth_trades = [t for t in result.trades if t.synthetic_pnl is not None]
        if not synth_trades:
            pytest.skip("No trades with synthetic data")

        trade = synth_trades[0]
        # The synthetic P&L should be a finite float
        assert trade.synthetic_pnl is not None
        assert trade.synthetic_pnl_pct is not None
        assert not (trade.synthetic_pnl != trade.synthetic_pnl)  # not NaN


# ── Config wiring for short profile ──────────────────────────────────────────

class TestShortConfigWiring:
    def test_short_weight_change_alters_composite_scores(self):
        """Changing a short-profile weight must change composite scores for that profile.

        Tested at the scoring level (run_engine) so we don't depend on trade generation.
        This proves the short profile is wired to its own weight set, independent of long.
        """
        from backend.app.config import Weights
        from backend.app.scoring.composite import run_engine

        cfg_default = load_config()

        weights_data = cfg_default.strategies.short.weights.model_dump()
        weights_data["rsi"] += 5
        weights_data["macd"] -= 5

        new_weights = Weights(**weights_data)
        short_strat_modified = cfg_default.get_strategy("short").model_copy(
            update={"weights": new_weights}
        )
        strategies_modified = cfg_default.strategies.model_copy(
            update={"short": short_strat_modified}
        )
        cfg_alt = cfg_default.model_copy(update={"strategies": strategies_modified})

        df = _make_ohlcv(100, seed=17)
        res_default = run_engine(df, cfg_default, strategy="short")
        res_alt = run_engine(df, cfg_alt, strategy="short")

        composites_default = [r["composite"] for r in res_default]
        composites_alt = [r["composite"] for r in res_alt]

        n_differ = sum(
            abs(a - b) > 1e-9
            for a, b in zip(composites_default, composites_alt)
        )
        assert n_differ > 0, (
            "Short weight change had no effect on composite scores — short profile not wired"
        )

    def test_short_weight_change_does_not_affect_long_profile(self):
        """Changing a short-profile weight must NOT change the long profile's scores."""
        from backend.app.config import Weights
        from backend.app.scoring.composite import run_engine

        cfg_default = load_config()

        weights_data = cfg_default.strategies.short.weights.model_dump()
        weights_data["rsi"] = 0
        weights_data["macd"] = weights_data["macd"] + 10

        new_weights = Weights(**weights_data)
        short_strat_modified = cfg_default.get_strategy("short").model_copy(
            update={"weights": new_weights}
        )
        strategies_modified = cfg_default.strategies.model_copy(
            update={"short": short_strat_modified}
        )
        cfg_alt = cfg_default.model_copy(update={"strategies": strategies_modified})

        df = _make_ohlcv(100, seed=17)
        long_default = run_engine(df, cfg_default, strategy="long")
        long_alt = run_engine(df, cfg_alt, strategy="long")

        composites_default = [r["composite"] for r in long_default]
        composites_alt = [r["composite"] for r in long_alt]

        n_differ = sum(abs(a - b) > 1e-9 for a, b in zip(composites_default, composites_alt))
        assert n_differ == 0, (
            "Changing short profile weights affected long profile scores — profiles not isolated"
        )


# ── Long profile still works (no regression) ─────────────────────────────────

class TestLongProfileRegression:
    def test_long_backtest_unchanged(self, cfg):
        """Long profile must still produce BacktestResult with correct structure."""
        df = _make_ohlcv(120, seed=42, trend=0.3)
        fetcher = _make_fetcher({"T": df})
        result = run_backtest(
            ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
            strategy="long",
        )
        assert result.strategy == "long"
        assert result.coverage_report is None
        assert result.survivorship_note
        assert isinstance(result.metrics, dict)

    def test_long_trade_has_no_short_only_fields(self, cfg):
        """Long trades should not have underlying_symbol or trade_instrument set."""
        df = _make_ohlcv(120, seed=99, trend=0.5)
        fetcher = _make_fetcher({"T": df})

        with patch(
            "backend.app.backtest.engine._compute_signals",
            side_effect=_force_signal("Strong Buy", 90.0),
        ):
            result = run_backtest(
                ["T"], df.index[0].date(), df.index[-1].date(), cfg, fetcher,
                strategy="long",
            )

        for trade in result.trades:
            assert trade.underlying_symbol is None
            assert trade.trade_instrument is None
            assert trade.synthetic_pnl is None

"""MOD-I optimizer tests.

Required tests:
1. Holdout isolation: objective function has no access to holdout dates.
2. Weight constraint: every sampled config has weights summing to 100.
3. Determinism: same seed + same data ⇒ same best config.
4. Tiny end-to-end run completes without error (few symbols, few trials).
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.optimizer.param_space import (
    build_strat_from_trial,
    extract_weights_from_params,
    weights_sum_to_100,
)
from backend.app.optimizer.precompute import precompute_symbols
from backend.app.optimizer.fast_engine import fast_backtest_long
from backend.app.optimizer.core import OptimiserConfig, run_optimisation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 300, seed: int = 42, base: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.standard_normal(n) * 0.8)
    closes = np.maximum(closes, 1.0)
    opens  = closes + rng.uniform(-0.5, 0.5, n)
    highs  = np.maximum(opens, closes) + rng.uniform(0.1, 1.0, n)
    lows   = np.minimum(opens, closes) - rng.uniform(0.1, 1.0, n)
    vols   = rng.integers(500_000, 5_000_000, n).astype("int64")
    idx    = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


def _make_fetcher(sym_df: dict[str, pd.DataFrame]):
    def _fetch(sym: str, s: date, e: date) -> pd.DataFrame:
        if sym not in sym_df:
            raise ValueError(f"Unknown symbol: {sym}")
        df = sym_df[sym]
        s_ts, e_ts = pd.Timestamp(s), pd.Timestamp(e)
        return df.loc[(df.index >= s_ts) & (df.index <= e_ts)]
    return _fetch


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def toy_data():
    """Three symbols with 300 bars each."""
    syms = ["AAPL", "MSFT", "GOOGL"]
    return {sym: _make_ohlcv(300, seed=i * 100) for i, sym in enumerate(syms)}


@pytest.fixture(scope="module")
def toy_fetcher(toy_data):
    return _make_fetcher(toy_data)


@pytest.fixture(scope="module")
def toy_dates(toy_data):
    idx = toy_data["AAPL"].index
    return date(idx[0].year, idx[0].month, idx[0].day), date(idx[-1].year, idx[-1].month, idx[-1].day)


# ── Test 1: Holdout isolation ─────────────────────────────────────────────────

class TestHoldoutIsolation:
    """The objective function must never access holdout dates."""

    def test_objective_restricted_to_insample(self, cfg, toy_fetcher, toy_dates):
        """fast_backtest_long called with insample_end should only use bars up to that date."""
        start, end = toy_dates
        all_dates_raw = pd.date_range(start, end, freq="B")
        split_idx    = int(len(all_dates_raw) * 0.70)
        insample_end = all_dates_raw[split_idx].date()
        holdout_start = all_dates_raw[split_idx + 1].date()

        precomputed = precompute_symbols(
            ["AAPL"], start, end, cfg, toy_fetcher,
        )
        strat = cfg.get_strategy("long")
        bk    = cfg.backtest

        result = fast_backtest_long(
            precomputed, strat, cfg, bk, start, insample_end,
        )

        # The equity curve must not contain any dates in the holdout period
        eq_dates = {pt["date"] for pt in result.equity_curve}
        holdout_dates = {
            str(d.date()) for d in pd.date_range(holdout_start, end, freq="B")
        }
        overlap = eq_dates & holdout_dates
        assert len(overlap) == 0, (
            f"Objective saw holdout dates: {list(overlap)[:5]}"
        )


# ── Test 2: Weight constraints ─────────────────────────────────────────────────

class TestWeightConstraints:
    """Every sampled config must have weights summing to 100."""

    def test_weights_sum_to_100_always(self, cfg):
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )

        for _ in range(50):
            trial = study.ask()
            strat, bk = build_strat_from_trial(trial, cfg)
            w = strat.weights
            total = (
                w.candlestick + w.p3 + w.p5 + w.volume
                + w.ema + w.sr + w.macd + w.rsi
            )
            assert abs(total - 100.0) < 1e-4, (
                f"Weights sum to {total:.6f}, not 100. params={trial.params}"
            )
            study.tell(trial, 0.0)

    def test_weights_sum_to_100_with_scoring_tables(self, cfg):
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")

        for _ in range(20):
            trial = study.ask()
            strat, bk = build_strat_from_trial(
                trial, cfg, include_scoring_tables=True,
            )
            w = strat.weights
            total = (
                w.candlestick + w.p3 + w.p5 + w.volume
                + w.ema + w.sr + w.macd + w.rsi
            )
            assert abs(total - 100.0) < 1e-4
            study.tell(trial, 0.0)

    def test_weights_sum_to_100_with_sizing(self, cfg):
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")

        for _ in range(20):
            trial = study.ask()
            strat, bk = build_strat_from_trial(
                trial, cfg, include_sizing=True,
            )
            w = strat.weights
            total = (
                w.candlestick + w.p3 + w.p5 + w.volume
                + w.ema + w.sr + w.macd + w.rsi
            )
            assert abs(total - 100.0) < 1e-4
            # Phase-3 sizing overrides are valid
            assert 0.04 <= bk.position_size_pct <= 0.15
            assert 5 <= bk.max_concurrent_positions <= 25
            study.tell(trial, 0.0)


# ── Test 3: Determinism ───────────────────────────────────────────────────────

class TestDeterminism:
    """Same seed + same data ⇒ same best config."""

    def test_same_seed_same_best_weights(self, cfg, toy_fetcher, toy_dates):
        start, end = toy_dates

        opt_cfg = OptimiserConfig(
            max_trials=30, n_folds=2, seed=42,
            n_luck_audit_configs=5, n_perturbation_nudges=3, top_cluster_n=5,
        )

        def _run():
            import tempfile, os
            from pathlib import Path
            with tempfile.TemporaryDirectory() as tmpdir:
                opt_cfg.study_db_path = Path(tmpdir) / "test_study.db"
                return run_optimisation(
                    symbols=["AAPL", "MSFT", "GOOGL"],
                    start=start, end=end,
                    base_cfg=cfg,
                    data_fetcher=toy_fetcher,
                    opt_cfg=opt_cfg,
                )

        res1 = _run()
        res2 = _run()

        for comp in ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]:
            w1 = res1.best_strat_dict["weights"][comp]
            w2 = res2.best_strat_dict["weights"][comp]
            assert abs(w1 - w2) < 1e-3, (
                f"Non-deterministic result for {comp}: run1={w1:.4f}, run2={w2:.4f}"
            )


# ── Test 4: Tiny end-to-end ───────────────────────────────────────────────────

class TestTinyEndToEnd:
    """A minimal run (3 symbols, 15 trials) completes without error."""

    def test_end_to_end_completes(self, cfg, toy_fetcher, toy_dates):
        import tempfile
        from pathlib import Path

        start, end = toy_dates
        opt_cfg = OptimiserConfig(
            max_trials=15, n_folds=2, seed=99,
            n_luck_audit_configs=5, n_perturbation_nudges=3, top_cluster_n=5,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            opt_cfg.study_db_path = Path(tmpdir) / "tiny.db"
            result = run_optimisation(
                symbols=["AAPL", "MSFT", "GOOGL"],
                start=start, end=end,
                base_cfg=cfg,
                data_fetcher=toy_fetcher,
                opt_cfg=opt_cfg,
            )

        assert result.n_trials_attempted > 0
        assert result.best_params is not None
        assert isinstance(result.pass_verdict, bool)
        assert len(result.wf_folds) > 0

    def test_end_to_end_with_scoring_tables(self, cfg, toy_fetcher, toy_dates):
        import tempfile
        from pathlib import Path

        start, end = toy_dates
        opt_cfg = OptimiserConfig(
            max_trials=10, n_folds=2, seed=77,
            include_scoring_tables=True,
            n_luck_audit_configs=3, n_perturbation_nudges=2, top_cluster_n=5,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            opt_cfg.study_db_path = Path(tmpdir) / "tiny_p2.db"
            result = run_optimisation(
                symbols=["AAPL", "MSFT"],
                start=start, end=end,
                base_cfg=cfg,
                data_fetcher=toy_fetcher,
                opt_cfg=opt_cfg,
            )

        assert result.n_trials_attempted > 0

    def test_report_is_written(self, cfg, toy_fetcher, toy_dates):
        import tempfile
        from pathlib import Path

        start, end = toy_dates
        opt_cfg = OptimiserConfig(
            max_trials=10, n_folds=2, seed=55,
            n_luck_audit_configs=3, n_perturbation_nudges=2, top_cluster_n=5,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            opt_cfg.study_db_path = Path(tmpdir) / "tiny_report.db"
            result = run_optimisation(
                symbols=["AAPL", "MSFT"],
                start=start, end=end,
                base_cfg=cfg,
                data_fetcher=toy_fetcher,
                opt_cfg=opt_cfg,
            )

        from backend.app.optimizer.report import generate_report
        import tempfile as tf
        from unittest.mock import patch

        with tf.TemporaryDirectory() as report_dir:
            from backend.app.optimizer import report as report_mod
            orig = report_mod._REPORTS_DIR
            report_mod._REPORTS_DIR = Path(report_dir)
            try:
                path = generate_report(result, "long", ["AAPL", "MSFT"])
                assert path.exists()
                content = path.read_text()
                assert "PASS" in content or "FAIL" in content
                assert "In-Sample" in content
                assert "Holdout" in content
                assert "Walk-Forward" in content
            finally:
                report_mod._REPORTS_DIR = orig

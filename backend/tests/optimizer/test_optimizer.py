"""Optimizer tests (Hidden-Divergence Confluence param space).

1. Holdout isolation: objective never sees holdout dates.
2. Param ranges: sampled entry/exit scores + thresholds stay in bounds.
3. Determinism: same seed + same data ⇒ same best config.
4. WF composite objective rewards consistency across folds.
5. Tiny end-to-end run completes and writes a report.
"""
from __future__ import annotations

import math
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.optimizer.param_space import build_strat_from_trial
from backend.app.optimizer.precompute import precompute_symbols
from backend.app.optimizer.fast_engine import fast_backtest_long
from backend.app.optimizer.core import OptimiserConfig, run_optimisation


def _make_ohlcv(n: int = 360, seed: int = 42, base: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.standard_normal(n) * 0.8)
    closes = np.maximum(closes, 1.0)
    opens = closes + rng.uniform(-0.5, 0.5, n)
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 1.0, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 1.0, n)
    vols = rng.integers(500_000, 5_000_000, n).astype("int64")
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx)


def _make_fetcher(sym_df: dict[str, pd.DataFrame]):
    def _fetch(sym: str, s: date, e: date) -> pd.DataFrame:
        if sym not in sym_df:
            raise ValueError(f"Unknown symbol: {sym}")
        df = sym_df[sym]
        return df.loc[(df.index >= pd.Timestamp(s)) & (df.index <= pd.Timestamp(e))]
    return _fetch


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def toy_data():
    return {sym: _make_ohlcv(360, seed=i * 100) for i, sym in enumerate(["AAA", "BBB", "CCC"])}


@pytest.fixture(scope="module")
def toy_fetcher(toy_data):
    return _make_fetcher(toy_data)


@pytest.fixture(scope="module")
def toy_dates(toy_data):
    idx = toy_data["AAA"].index
    return idx[0].date(), idx[-1].date()


# ── Holdout isolation ──────────────────────────────────────────────────────────

def test_objective_restricted_to_insample(cfg, toy_fetcher, toy_dates):
    start, end = toy_dates
    all_dates = pd.date_range(start, end, freq="B")
    split = int(len(all_dates) * 0.70)
    insample_end = all_dates[split].date()
    holdout_start = all_dates[split + 1].date()

    pc = precompute_symbols(["AAA"], start, end, cfg, toy_fetcher)
    result = fast_backtest_long(pc, cfg.get_strategy("hidden_div"), cfg, cfg.backtest, start, insample_end)

    eq_dates = {pt["date"] for pt in result.equity_curve}
    holdout = {str(d.date()) for d in pd.date_range(holdout_start, end, freq="B")}
    assert len(eq_dates & holdout) == 0


# ── Param ranges ────────────────────────────────────────────────────────────────

def test_sampled_params_in_range(cfg):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=1))
    for _ in range(40):
        trial = study.ask()
        strat, bk = build_strat_from_trial(trial, cfg, include_sizing=True)
        for name in ("macd_hidden_bull", "rsi_hidden_bull", "rsi_zone", "demark_td9_buy"):
            assert 0.0 <= getattr(strat.entry.weights, name) <= 50.0
        for name in ("demark_td13_sell", "macd_regular_bear", "rsi_regular_bear", "demark_td9_sell"):
            assert 0.0 <= getattr(strat.exit.weights, name) <= 50.0
        assert 30.0 <= strat.entry.threshold <= 100.0
        assert 15.0 <= strat.exit.threshold <= 80.0
        assert 0.04 <= bk.position_size_pct <= 0.15
        assert 5 <= bk.max_concurrent_positions <= 25
        study.tell(trial, 0.0)


def test_windows_tuned_when_flag_set(cfg):
    import optuna
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=2))
    trial = study.ask()
    strat, _ = build_strat_from_trial(trial, cfg, include_scoring_tables=True)
    assert 3 <= strat.entry.conf_window <= 20
    assert 2 <= strat.exit.conf_window <= 15


# ── Composite objective math ────────────────────────────────────────────────────

def _composite_score(fold_sharpes, max_dd):
    mean_wf = sum(fold_sharpes) / len(fold_sharpes)
    std_wf = math.sqrt(sum((s - mean_wf) ** 2 for s in fold_sharpes) / len(fold_sharpes))
    dd_pen = 1.0 * max(0.0, max_dd - 15.0) / 100.0
    return mean_wf - 0.5 * std_wf - dd_pen


def test_consistent_beats_volatile_same_mean():
    assert _composite_score([1.0, 1.0, 1.0, 1.0], 10.0) > _composite_score([0.5, 0.5, 1.5, 1.5], 10.0)


def test_excess_drawdown_reduces_score():
    assert _composite_score([1.2] * 4, 25.0) < _composite_score([1.2] * 4, 12.0)


# ── Determinism + end-to-end ─────────────────────────────────────────────────────

def test_determinism_same_seed(cfg, toy_fetcher, toy_dates):
    start, end = toy_dates

    def _run():
        with tempfile.TemporaryDirectory() as tmp:
            opt_cfg = OptimiserConfig(
                max_trials=20, n_folds=2, seed=42,
                n_luck_audit_configs=4, n_perturbation_nudges=2, top_cluster_n=5,
                study_db_path=Path(tmp) / "s.db",
            )
            return run_optimisation(["AAA", "BBB", "CCC"], start, end, cfg, toy_fetcher, opt_cfg)

    r1 = _run()
    r2 = _run()
    for side in ("entry", "exit"):
        for name, v in r1.best_strat_dict[side]["weights"].items():
            assert abs(v - r2.best_strat_dict[side]["weights"][name]) < 1e-3
        assert abs(r1.best_strat_dict[side]["threshold"] - r2.best_strat_dict[side]["threshold"]) < 1e-3


def test_end_to_end_and_report(cfg, toy_fetcher, toy_dates):
    start, end = toy_dates
    with tempfile.TemporaryDirectory() as tmp:
        opt_cfg = OptimiserConfig(
            max_trials=12, n_folds=2, seed=99,
            n_luck_audit_configs=4, n_perturbation_nudges=2, top_cluster_n=5,
            study_db_path=Path(tmp) / "e2e.db",
        )
        result = run_optimisation(["AAA", "BBB", "CCC"], start, end, cfg, toy_fetcher, opt_cfg)

    assert result.n_trials_attempted > 0
    assert result.best_params is not None
    assert isinstance(result.pass_verdict, bool)
    assert len(result.wf_folds) > 0

    from backend.app.optimizer import report as report_mod
    from backend.app.optimizer.report import generate_report
    with tempfile.TemporaryDirectory() as report_dir:
        orig = report_mod._REPORTS_DIR
        report_mod._REPORTS_DIR = Path(report_dir)
        try:
            path = generate_report(result, "long", ["AAA", "BBB", "CCC"])
            content = path.read_text()
            assert path.exists()
            assert any(x in content for x in ("ROBUST", "SUSPECT", "OVERFIT"))
            assert "Component Scores" in content
            assert "Walk-Forward" in content
        finally:
            report_mod._REPORTS_DIR = orig

"""Walk-forward validation: split history into N folds, optimise on each train slice,
validate on the following unseen slice, then stitch all out-of-sample results.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import optuna

from backend.app.backtest.metrics import compute_strategy_metrics
from backend.app.config import AppConfig, BacktestConfig
from backend.app.optimizer.fast_engine import fast_backtest_long
from backend.app.optimizer.param_space import build_strat_from_trial
from backend.app.optimizer.precompute import PrecomputedSymbol

logger = logging.getLogger(__name__)

optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class WalkForwardFold:
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    best_params: dict
    train_sharpe: float
    test_metrics: dict


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold] = field(default_factory=list)
    # Stitched out-of-sample equity curve (concatenation of test folds)
    oos_equity_curve: list[dict] = field(default_factory=list)
    oos_metrics: dict = field(default_factory=dict)


def _date_quantile(dates: list[date], q: float) -> date:
    """Return the date at quantile q in sorted date list."""
    idx = min(int(len(dates) * q), len(dates) - 1)
    return dates[idx]


def run_walk_forward(
    precomputed: dict[str, PrecomputedSymbol],
    full_start: date,
    full_end: date,
    base_cfg: AppConfig,
    n_folds: int = 4,
    max_trials_per_fold: int = 500,
    max_drawdown_limit: float = 0.25,
    include_scoring_tables: bool = False,
    include_sizing: bool = False,
    seed: int = 42,
) -> WalkForwardResult:
    """Anchored expanding-window walk-forward validation.

    Fold k: train on [full_start, split_k), test on [split_k, split_{k+1}).
    """
    all_dates = sorted({d for pc in precomputed.values() for d in pc.dates
                        if full_start <= d <= full_end})
    if len(all_dates) < n_folds * 2 * 30:
        logger.warning("Insufficient dates for %d walk-forward folds", n_folds)
        return WalkForwardResult()

    # Build fold boundaries: split the full range into n_folds+1 equal segments
    # Train ends at each split; test spans the next segment.
    segment_len = len(all_dates) // (n_folds + 1)
    split_points: list[date] = [
        all_dates[min((k + 1) * segment_len, len(all_dates) - 1)]
        for k in range(n_folds)
    ]

    result = WalkForwardResult()
    oos_trades_all: list = []
    oos_equity_all: list[dict] = []
    base_equity = base_cfg.backtest.initial_fund

    for k, test_start in enumerate(split_points):
        train_end_idx = all_dates.index(test_start) - 1
        if train_end_idx < 30:
            continue
        train_end = all_dates[train_end_idx]

        test_end_idx = (
            all_dates.index(split_points[k + 1]) - 1
            if k + 1 < len(split_points)
            else len(all_dates) - 1
        )
        test_end = all_dates[test_end_idx]

        if test_end <= test_start:
            continue

        logger.info(
            "Walk-forward fold %d/%d: train=%s→%s, test=%s→%s",
            k + 1, n_folds, full_start, train_end, test_start, test_end,
        )

        # Optimise on the train slice for this fold
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=seed + k),
        )

        def _objective(trial: optuna.Trial) -> float:
            strat, bk = build_strat_from_trial(
                trial, base_cfg,
                include_scoring_tables=include_scoring_tables,
                include_sizing=include_sizing,
            )
            res = fast_backtest_long(
                precomputed, strat, base_cfg, bk,
                full_start, train_end,
                include_scoring_tables=include_scoring_tables,
            )
            m = res.metrics
            if m.get("max_drawdown", 100) > max_drawdown_limit * 100:
                raise optuna.exceptions.TrialPruned()
            return m.get("sharpe_ratio", 0.0)

        study.optimize(_objective, n_trials=max_trials_per_fold, show_progress_bar=False)

        best = study.best_trial
        best_strat, best_bk = build_strat_from_trial(
            best, base_cfg,
            include_scoring_tables=include_scoring_tables,
            include_sizing=include_sizing,
        )

        # Validate on the unseen test slice
        test_res = fast_backtest_long(
            precomputed, best_strat, base_cfg, best_bk,
            test_start, test_end,
            include_scoring_tables=include_scoring_tables,
        )

        # Rescale equity curve to start from running OOS equity level
        if oos_equity_all:
            last_oos_equity = oos_equity_all[-1]["equity"]
        else:
            last_oos_equity = base_equity

        if test_res.equity_curve:
            test_start_equity = test_res.equity_curve[0]["equity"]
            if test_start_equity > 0:
                scale = last_oos_equity / test_start_equity
                for pt in test_res.equity_curve:
                    oos_equity_all.append({
                        "date": pt["date"],
                        "equity": pt["equity"] * scale,
                        "n_open": pt["n_open"],
                    })
            else:
                oos_equity_all.extend(test_res.equity_curve)
        else:
            oos_equity_all.append({"date": str(test_start), "equity": last_oos_equity, "n_open": 0})

        oos_trades_all.extend(test_res.trades)

        fold = WalkForwardFold(
            fold=k + 1,
            train_start=full_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            best_params=best.params,
            train_sharpe=best.value if best.value is not None else 0.0,
            test_metrics=test_res.metrics,
        )
        result.folds.append(fold)
        logger.info(
            "  Fold %d: train Sharpe=%.3f, test Sharpe=%.3f, test DD=%.1f%%",
            k + 1, fold.train_sharpe,
            test_res.metrics.get("sharpe_ratio", 0.0),
            test_res.metrics.get("max_drawdown", 0.0),
        )

    # Aggregate OOS metrics across all test folds
    if oos_equity_all:
        result.oos_equity_curve = oos_equity_all
        result.oos_metrics = compute_strategy_metrics(
            oos_trades_all, oos_equity_all, base_equity, base_cfg.backtest.risk_free_rate
        )
    return result

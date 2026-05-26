"""Fast backtest engine using pre-computed indicator data.

Reuses the existing _walk_dates simulation loop.  The only per-trial work is
building _SymbolData from pre-computed component scores (Phase 1) or by
re-running scoring functions with new tables (Phase 2).
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from backend.app.backtest.engine import (
    BacktestResult,
    _SymbolData,
    _walk_dates,
    _run_benchmark,
)
from backend.app.backtest.metrics import compute_strategy_metrics, build_comparison
from backend.app.config import AppConfig, BacktestConfig
from backend.app.optimizer.precompute import PrecomputedSymbol, recompute_scores
from backend.app.scoring.composite import score_bar

logger = logging.getLogger(__name__)

_MIN_BARS = 50


def _build_sym_data(
    pc: PrecomputedSymbol,
    scores: dict,
    strat,
    start: date,
    end: date,
) -> _SymbolData | None:
    """Slice pre-computed (or freshly-computed) scores to [start, end] and build _SymbolData."""
    dates_sliced = pc.dates_in_range(start, end)
    if len(dates_sliced) < _MIN_BARS:
        return None

    # Build signals using pre-computed scores for the full period and sliced regime
    signals: dict[date, dict] = {}
    for d in dates_sliced:
        i = pc.date_pos(d)
        if i is None:
            continue
        regime = {
            "long_allowed":  bool(pc.regime_df["long_allowed"].iat[i]),
            "short_allowed": bool(pc.regime_df["short_allowed"].iat[i]),
        }
        sub = {name: float(s.iat[i]) for name, s in scores.items()}
        bar_result = score_bar(sub, strat.weights, regime, strat.thresholds)
        signals[d] = bar_result

    return _SymbolData(
        dates=dates_sliced,
        bars={d: pc.bars[d] for d in dates_sliced},
        signals=signals,
        atr={d: pc.atr[d] for d in dates_sliced},
    )


def fast_backtest_long(
    precomputed: dict[str, PrecomputedSymbol],
    strat,
    base_cfg: AppConfig,
    bk: BacktestConfig,
    start: date,
    end: date,
    include_scoring_tables: bool = False,
) -> BacktestResult:
    """Run a long backtest using pre-computed indicator data.

    ``include_scoring_tables=False``: use default component scores (Phase-1 fast mode).
    ``include_scoring_tables=True``: re-run scoring functions with strat scoring tables.
    """
    sym_data: dict[str, _SymbolData] = {}
    for sym, pc in precomputed.items():
        scores = recompute_scores(pc, strat) if include_scoring_tables else pc.default_scores
        sd = _build_sym_data(pc, scores, strat, start, end)
        if sd is not None:
            sym_data[sym] = sd

    if not sym_data:
        empty_metrics = {"n_trades": 0, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "cagr": 0.0}
        return BacktestResult(
            metrics=empty_metrics, trades=[], equity_curve=[],
            params={"strategy": "long", "start": str(start), "end": str(end)},
            strategy="long",
        )

    all_dates = sorted({d for sd in sym_data.values() for d in sd.dates})
    closed_trades, equity_curve, constraint_counts = _walk_dates(
        all_dates=all_dates, sym_data=sym_data, cfg=base_cfg, bk=bk, strategy="long",
    )

    metrics = compute_strategy_metrics(
        closed_trades, equity_curve, bk.initial_fund, bk.risk_free_rate
    )

    return BacktestResult(
        metrics=metrics, trades=closed_trades, equity_curve=equity_curve,
        params={"strategy": "long", "start": str(start), "end": str(end),
                "n_symbols": len(sym_data)},
        strategy="long",
        constraint_counts=constraint_counts,
    )


def fast_backtest_with_benchmark(
    precomputed: dict[str, PrecomputedSymbol],
    strat,
    base_cfg: AppConfig,
    bk: BacktestConfig,
    start: date,
    end: date,
    data_fetcher,
    include_scoring_tables: bool = False,
) -> BacktestResult:
    """Full backtest including benchmark comparison (used for holdout/walk-forward reports)."""
    result = fast_backtest_long(precomputed, strat, base_cfg, bk, start, end, include_scoring_tables)

    benchmark_metrics, benchmark_eq = _run_benchmark(data_fetcher, start, end, bk)
    comparison = build_comparison(result.metrics, benchmark_metrics, bk)

    return BacktestResult(
        metrics=result.metrics,
        trades=result.trades,
        equity_curve=result.equity_curve,
        params=result.params,
        strategy="long",
        benchmark_metrics=benchmark_metrics,
        benchmark_equity_curve=benchmark_eq,
        comparison=comparison,
        constraint_counts=result.constraint_counts,
    )

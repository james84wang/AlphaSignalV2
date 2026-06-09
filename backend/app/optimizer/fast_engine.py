"""Fast backtest using pre-computed confluence events.

Each trial only re-runs the cheap scoring step (:func:`compute_signals`) over the
pre-computed events, then reuses the production ``_walk_dates`` simulation loop.
"""
from __future__ import annotations

import logging
from datetime import date

from backend.app.backtest.engine import (
    BacktestResult,
    _SymbolData,
    _walk_dates,
    _run_benchmark,
)
from backend.app.backtest.metrics import compute_strategy_metrics, build_comparison
from backend.app.config import AppConfig, BacktestConfig, StrategyConfig
from backend.app.optimizer.precompute import PrecomputedSymbol
from backend.app.scoring.confluence import compute_signals

logger = logging.getLogger(__name__)

_MIN_BARS = 50


def _build_sym_data(
    pc: PrecomputedSymbol,
    strat: StrategyConfig,
    start: date,
    end: date,
) -> _SymbolData | None:
    """Score the full-range events for this strat, then slice to [start, end]."""
    dates_sliced = pc.dates_in_range(start, end)
    if len(dates_sliced) < _MIN_BARS:
        return None

    sa = compute_signals(pc.events, strat.entry, strat.exit)  # full range (cooldown is stateful)

    signals: dict[date, dict] = {}
    for d in dates_sliced:
        i = pc.date_pos(d)
        if i is None:
            continue
        signals[d] = {"signal": sa.signals[i], "composite": float(sa.composite[i])}

    return _SymbolData(
        dates=dates_sliced,
        bars={d: pc.bars[d] for d in dates_sliced},
        signals=signals,
        atr={d: pc.atr[d] for d in dates_sliced},
    )


def fast_backtest_long(
    precomputed: dict[str, PrecomputedSymbol],
    strat: StrategyConfig,
    base_cfg: AppConfig,
    bk: BacktestConfig,
    start: date,
    end: date,
    include_scoring_tables: bool = False,  # accepted for signature compat; unused
) -> BacktestResult:
    """Run a long backtest using pre-computed events."""
    sym_data: dict[str, _SymbolData] = {}
    for sym, pc in precomputed.items():
        sd = _build_sym_data(pc, strat, start, end)
        if sd is not None:
            sym_data[sym] = sd

    if not sym_data:
        empty_metrics = {"n_trades": 0, "sharpe_ratio": 0.0, "max_drawdown": 0.0, "cagr": 0.0}
        return BacktestResult(
            metrics=empty_metrics, trades=[], equity_curve=[],
            params={"strategy": "hidden_div", "start": str(start), "end": str(end)},
            strategy="hidden_div",
        )

    all_dates = sorted({d for sd in sym_data.values() for d in sd.dates})
    closed_trades, equity_curve, constraint_counts = _walk_dates(
        all_dates=all_dates, sym_data=sym_data, cfg=base_cfg, bk=bk,
    )

    metrics = compute_strategy_metrics(
        closed_trades, equity_curve, bk.initial_fund, bk.risk_free_rate
    )

    return BacktestResult(
        metrics=metrics, trades=closed_trades, equity_curve=equity_curve,
        params={"strategy": "hidden_div", "start": str(start), "end": str(end),
                "n_symbols": len(sym_data)},
        strategy="hidden_div",
        constraint_counts=constraint_counts,
    )


def fast_backtest_with_benchmark(
    precomputed: dict[str, PrecomputedSymbol],
    strat: StrategyConfig,
    base_cfg: AppConfig,
    bk: BacktestConfig,
    start: date,
    end: date,
    data_fetcher,
    include_scoring_tables: bool = False,
) -> BacktestResult:
    """Full backtest including benchmark comparison (used for holdout/walk-forward reports)."""
    result = fast_backtest_long(precomputed, strat, base_cfg, bk, start, end)

    benchmark_metrics, benchmark_eq = _run_benchmark(data_fetcher, start, end, bk)
    comparison = build_comparison(result.metrics, benchmark_metrics, bk)

    return BacktestResult(
        metrics=result.metrics,
        trades=result.trades,
        equity_curve=result.equity_curve,
        params=result.params,
        strategy="hidden_div",
        benchmark_metrics=benchmark_metrics,
        benchmark_equity_curve=benchmark_eq,
        comparison=comparison,
        constraint_counts=result.constraint_counts,
    )

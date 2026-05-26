"""Optuna parameter space and AppConfig builder for the optimiser.

Phase 1 (always active): 8 component weights (sum=100) + signal thresholds.
Phase 2 (--include-scoring-tables): per-component score multipliers.
Phase 3 (--include-sizing): position_size_pct + max_concurrent_positions.
"""
from __future__ import annotations

from copy import deepcopy

import optuna

from backend.app.config import (
    AppConfig, BacktestConfig, StrategyConfig, Weights, Thresholds,
    CandlestickScores, CandlestickConfig,
    P3Scores, P3Config,
    P5Scores, P5Config,
    EmaStackingScores, EmaCrossScores, EmaConfig,
    SrScores, SrConfig,
    MacdMicroSignals, MacdConfig,
    RsiScores, RsiConfig,
    StrategiesMap,
)

_WEIGHT_NAMES = ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]


def suggest_weights(trial: optuna.Trial) -> dict[str, float]:
    """Suggest 8 component weights summing to exactly 100.

    Samples each weight uniformly in [0.5, 40], then normalises.
    This is equivalent to Dirichlet(1,1,…,1) but with a max-weight cap of ~60%.
    """
    raw = {n: trial.suggest_float(f"w_{n}", 0.5, 40.0) for n in _WEIGHT_NAMES}
    total = sum(raw.values())
    return {n: v / total * 100.0 for n, v in raw.items()}


def suggest_thresholds(trial: optuna.Trial) -> dict[str, float]:
    """Suggest buy/sell signal thresholds with symmetry enforced."""
    strong_buy = trial.suggest_float("t_strong_buy", 50.0, 90.0)
    buy        = trial.suggest_float("t_buy", 25.0, strong_buy - 5.0)
    return {
        "strong_buy":  strong_buy,
        "buy":         buy,
        "sell":        -buy,
        "strong_sell": -strong_buy,
    }


def _scale_scores(base: dict, mult: float) -> dict:
    """Multiply every score in a table by mult, preserving sign."""
    return {k: v * mult for k, v in base.items()}


def suggest_scoring_multipliers(
    trial: optuna.Trial, base_strat: StrategyConfig
) -> dict[str, float]:
    """Suggest per-component score scale multipliers for Phase-2."""
    return {
        comp: trial.suggest_float(f"score_mult_{comp}", 0.3, 2.5)
        for comp in _WEIGHT_NAMES
    }


def build_strat_from_trial(
    trial: optuna.Trial,
    base_cfg: AppConfig,
    include_scoring_tables: bool = False,
    include_sizing: bool = False,
) -> tuple[StrategyConfig, BacktestConfig]:
    """Build a new (StrategyConfig, BacktestConfig) from trial parameters.

    Returns the modified strategy config and backtest config (Phase-3 may change
    sizing params; otherwise bk is returned unchanged).
    """
    base_strat = base_cfg.get_strategy("long")
    base_dict  = base_strat.model_dump()

    # ── Phase 1: weights and thresholds ──────────────────────────────────────
    base_dict["weights"]    = suggest_weights(trial)
    base_dict["thresholds"] = suggest_thresholds(trial)

    # ── Phase 2: per-component scoring table multipliers ─────────────────────
    if include_scoring_tables:
        mults = suggest_scoring_multipliers(trial, base_strat)

        cs_scores = {k: v * mults["candlestick"]
                     for k, v in base_dict["candlestick"]["scores"].items()}
        base_dict["candlestick"]["scores"] = cs_scores

        p3_scores = {k: v * mults["p3"]
                     for k, v in base_dict["p3"]["scores"].items()}
        base_dict["p3"]["scores"] = p3_scores

        p5_scores = {k: v * mults["p5"]
                     for k, v in base_dict["p5"]["scores"].items()}
        base_dict["p5"]["scores"] = p5_scores

        # Volume buckets: scale all bucket scores
        for bucket in base_dict["volume"]["bullish_buckets"]:
            bucket["score"] = bucket["score"] * mults["volume"]

        ema_stack = {k: v * mults["ema"]
                     for k, v in base_dict["ema"]["stacking_scores"].items()}
        ema_cross = {k: v * mults["ema"]
                     for k, v in base_dict["ema"]["cross_scores"].items()}
        base_dict["ema"]["stacking_scores"] = ema_stack
        base_dict["ema"]["cross_scores"]    = ema_cross

        sr_scores = {k: v * mults["sr"]
                     for k, v in base_dict["sr"]["scores"].items()}
        base_dict["sr"]["scores"] = sr_scores

        macd_signals = {k: v * mults["macd"]
                        for k, v in base_dict["macd"]["micro_signals"].items()}
        base_dict["macd"]["micro_signals"] = macd_signals

        rsi_scores = {k: v * mults["rsi"]
                      for k, v in base_dict["rsi"]["scores"].items()}
        base_dict["rsi"]["scores"] = rsi_scores

    new_strat = StrategyConfig.model_validate(base_dict)

    # ── Phase 3: position sizing ──────────────────────────────────────────────
    bk = base_cfg.backtest
    if include_sizing:
        pos_size_pct = trial.suggest_float("pos_size_pct", 0.04, 0.15)
        max_concurrent = trial.suggest_int("max_concurrent", 5, 25)
        bk = bk.model_copy(update={
            "position_size_pct": pos_size_pct,
            "max_concurrent_positions": max_concurrent,
        })

    return new_strat, bk


def weights_sum_to_100(params: dict) -> bool:
    """Verify that the weight parameters in a completed trial sum to 100."""
    raw = [params.get(f"w_{n}", 0.0) for n in _WEIGHT_NAMES]
    total = sum(raw)
    if total == 0:
        return False
    normalised = sum(v / total * 100.0 for v in raw)
    return abs(normalised - 100.0) < 1e-4


def extract_weights_from_params(params: dict) -> dict[str, float]:
    """Reconstruct normalised weights from a trial's params dict."""
    raw = {n: params.get(f"w_{n}", 1.0) for n in _WEIGHT_NAMES}
    total = sum(raw.values())
    return {n: v / total * 100.0 for n, v in raw.items()}

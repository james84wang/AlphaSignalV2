"""Optuna parameter space and StrategyConfig builder for the optimiser.

Always active: the 4 entry component scores, 4 exit component scores, and the
entry (buy) + exit (sell) thresholds.
``--include-scoring-tables`` (repurposed): also tune the confluence windows.
``--include-sizing``: also tune position_size_pct + max_concurrent_positions.
"""
from __future__ import annotations

import optuna

from backend.app.config import AppConfig, BacktestConfig, StrategyConfig

ENTRY_WEIGHTS = ["macd_hidden_bull", "rsi_hidden_bull", "rsi_zone", "demark_td9_buy"]
EXIT_WEIGHTS = ["demark_td13_sell", "macd_regular_bear", "rsi_regular_bear", "demark_td9_sell"]

# Param keys used in the Optuna trial (and reconstructed in core.py / perturbation).
ENTRY_PARAM = {w: f"ew_{w}" for w in ENTRY_WEIGHTS}
EXIT_PARAM = {w: f"xw_{w}" for w in EXIT_WEIGHTS}


def build_strat_from_trial(
    trial: optuna.Trial,
    base_cfg: AppConfig,
    include_scoring_tables: bool = False,
    include_sizing: bool = False,
) -> tuple[StrategyConfig, BacktestConfig]:
    """Build a (StrategyConfig, BacktestConfig) from trial parameters."""
    base = base_cfg.get_strategy("hidden_div").model_dump()

    for w in ENTRY_WEIGHTS:
        base["entry"]["weights"][w] = trial.suggest_float(ENTRY_PARAM[w], 0.0, 50.0)
    for w in EXIT_WEIGHTS:
        base["exit"]["weights"][w] = trial.suggest_float(EXIT_PARAM[w], 0.0, 50.0)

    base["entry"]["threshold"] = trial.suggest_float("entry_threshold", 30.0, 100.0)
    base["exit"]["threshold"] = trial.suggest_float("exit_threshold", 15.0, 80.0)

    if include_scoring_tables:  # repurposed: tune confluence windows
        base["entry"]["conf_window"] = trial.suggest_int("entry_conf_window", 3, 20)
        base["exit"]["conf_window"] = trial.suggest_int("exit_conf_window", 2, 15)

    new_strat = StrategyConfig.model_validate(base)

    bk = base_cfg.backtest
    if include_sizing:
        bk = bk.model_copy(update={
            "position_size_pct": trial.suggest_float("pos_size_pct", 0.04, 0.15),
            "max_concurrent_positions": trial.suggest_int("max_concurrent", 5, 25),
        })

    return new_strat, bk


def weights_from_params(params: dict) -> dict[str, float]:
    """Reconstruct the 8 raw entry/exit weights from a trial's params dict."""
    out: dict[str, float] = {}
    for w in ENTRY_WEIGHTS:
        out[w] = params.get(ENTRY_PARAM[w], 0.0)
    for w in EXIT_WEIGHTS:
        out[w] = params.get(EXIT_PARAM[w], 0.0)
    return out

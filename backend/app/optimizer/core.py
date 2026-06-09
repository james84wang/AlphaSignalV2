"""Main optimisation pipeline.

Sequence:
  1. Pre-load + pre-compute data for all symbols.
  2. Optimise on the in-sample slice (first 70% of the date range).
     Objective: maximise Sharpe, reject configs where max_drawdown > limit.
  3. Validate the best config on the holdout slice (last 30%).
  4. Walk-forward validation (4 folds over the full range).
  5. Anti-overfitting analysis (luck audit, perturbation, cluster check).
  6. Save: candidate config YAML, SQLite study, markdown report.

The live config.yaml is NEVER modified; winners are saved to
config.candidate.<strategy>.yaml for manual promotion.
"""
from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

import optuna
import pandas as pd
import yaml

from backend.app.config import AppConfig, BacktestConfig, StrategyConfig
from backend.app.optimizer.fast_engine import fast_backtest_long, fast_backtest_with_benchmark
from backend.app.optimizer.param_space import (
    ENTRY_PARAM,
    ENTRY_WEIGHTS,
    EXIT_PARAM,
    EXIT_WEIGHTS,
    build_strat_from_trial,
    weights_from_params,
)
from backend.app.optimizer.precompute import PrecomputedSymbol, precompute_symbols
from backend.app.optimizer.walk_forward import run_walk_forward

optuna.logging.set_verbosity(optuna.logging.WARNING)
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR   = _REPO_ROOT / "data"
_REPORTS_DIR = _REPO_ROOT / "reports"


@dataclass
class OptimiserConfig:
    strategy: Literal["hidden_div"] = "hidden_div"
    years: int = 5
    insample_ratio: float = 0.70
    max_trials: int = 2000
    n_folds: int = 4
    max_drawdown_limit: float = 0.25   # 25% hard constraint
    seed: int = 42
    include_scoring_tables: bool = False
    include_sizing: bool = False
    n_perturbation_nudges: int = 12
    n_luck_audit_configs: int = 50
    top_cluster_n: int = 20
    study_db_path: Path | None = None  # defaults to data/optimizer/study_<date>.db


@dataclass
class OptimisationResult:
    best_params: dict
    best_strat_dict: dict
    insample_metrics: dict
    holdout_metrics: dict
    holdout_benchmark_metrics: dict
    benchmark_vs_spy_metrics: dict     # extra SPY comparison
    wf_metrics: dict
    wf_folds: list
    luck_audit: dict
    perturbation_results: list[dict]
    cluster_analysis: dict
    insample_start: date
    insample_end: date
    holdout_start: date
    holdout_end: date
    wall_clock_seconds: float
    n_trials_attempted: int
    n_trials_in_sample_beat_benchmark: int
    pass_verdict: bool
    verdict_tier: str = "OVERFIT"   # ROBUST | SUSPECT | OVERFIT
    verdict_notes: list[str] = field(default_factory=list)
    # Best trial's composite score and its components (from objective function)
    best_composite_score: float = 0.0
    best_trial_wf_mean: float = 0.0
    best_trial_wf_std: float = 0.0
    best_trial_wf_fold_sharpes: list[float] = field(default_factory=list)
    best_trial_max_dd_pct: float = 0.0
    best_trial_dd_penalty: float = 0.0
    # Per-trial records for CSV export (one dict per completed trial)
    trial_records: list[dict] = field(default_factory=list)


# ── Public entry point ─────────────────────────────────────────────────────────

def run_optimisation(
    symbols: list[str],
    start: date,
    end: date,
    base_cfg: AppConfig,
    data_fetcher: Callable,
    opt_cfg: OptimiserConfig | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> OptimisationResult:
    """Full optimisation pipeline. Returns OptimisationResult with all findings.

    ``progress_callback(n_done, n_total, phase)`` (optional) is invoked while the
    search runs so a UI can show a live progress bar; ``n_total`` is the trial
    budget, ``n_done`` the trials completed so far.
    """
    if opt_cfg is None:
        opt_cfg = OptimiserConfig()

    t0 = time.perf_counter()

    # ── 1. Pre-compute ────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0, opt_cfg.max_trials, "Loading data & indicators")
    logger.info("Pre-computing indicators for %d symbols…", len(symbols))
    precomputed = precompute_symbols(
        symbols, start, end, base_cfg, data_fetcher,
        include_scoring_tables=opt_cfg.include_scoring_tables,
    )
    if not precomputed:
        raise RuntimeError("No symbols loaded — cannot optimise.")

    # ── 2. Date split ─────────────────────────────────────────────────────────
    all_dates = sorted({d for pc in precomputed.values() for d in pc.dates})
    split_idx = int(len(all_dates) * opt_cfg.insample_ratio)
    insample_end = all_dates[split_idx]
    holdout_start = all_dates[split_idx + 1]

    logger.info(
        "Date split: in-sample %s → %s (%.0f%%), holdout %s → %s",
        all_dates[0], insample_end, opt_cfg.insample_ratio * 100,
        holdout_start, all_dates[-1],
    )

    # ── 3. In-sample optimisation ─────────────────────────────────────────────
    db_dir = _DATA_DIR / "optimizer"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = opt_cfg.study_db_path or (
        db_dir / f"study_{opt_cfg.strategy}_{date.today()}.db"
    )
    storage = f"sqlite:///{db_path}"

    study = optuna.create_study(
        study_name=f"optimize_{opt_cfg.strategy}_{date.today()}",
        storage=storage,
        direction="maximize",
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=opt_cfg.seed),
    )

    logger.info(
        "Starting in-sample optimisation: %d trials, seed=%d",
        opt_cfg.max_trials, opt_cfg.seed,
    )

    # Walk-forward CV fold windows — all within in-sample, holdout never touched.
    # Expanding windows: reserve 1/(n_folds+1) of in-sample for initial training,
    # then n_folds equal-sized test windows.  Folds span different market regimes
    # (including any bear-market periods) so no single regime can dominate.
    insample_dates = [d for d in all_dates if d <= insample_end]
    n_cv_folds   = opt_cfg.n_folds
    cv_test_size = len(insample_dates) // (n_cv_folds + 1)
    cv_fold_windows: list[tuple[date, date]] = []
    for _k in range(n_cv_folds):
        _ts_idx = cv_test_size * (_k + 1)
        _te_idx = min(cv_test_size * (_k + 2) - 1, len(insample_dates) - 1)
        cv_fold_windows.append((insample_dates[_ts_idx], insample_dates[_te_idx]))

    logger.info(
        "CV fold windows (in-sample only): %s",
        [(str(s), str(e)) for s, e in cv_fold_windows],
    )

    def _objective(trial: optuna.Trial) -> float:
        strat, bk = build_strat_from_trial(
            trial, base_cfg,
            include_scoring_tables=opt_cfg.include_scoring_tables,
            include_sizing=opt_cfg.include_sizing,
        )
        # Evaluate the config on each CV fold's test window (no re-optimisation per fold)
        fold_sharpes: list[float] = []
        fold_cagrs:   list[float] = []
        fold_dds:     list[float] = []
        for f_start, f_end in cv_fold_windows:
            res = fast_backtest_long(
                precomputed, strat, base_cfg, bk,
                f_start, f_end,
                include_scoring_tables=opt_cfg.include_scoring_tables,
            )
            fold_sharpes.append(res.metrics.get("sharpe_ratio", 0.0))
            fold_cagrs.append(res.metrics.get("cagr", 0.0))
            fold_dds.append(res.metrics.get("max_drawdown", 100.0))

        max_dd   = max(fold_dds)
        if max_dd > opt_cfg.max_drawdown_limit * 100:
            raise optuna.exceptions.TrialPruned()

        # Composite: reward mean fold Sharpe, penalise cross-fold variance and excess DD
        mean_wf  = sum(fold_sharpes) / len(fold_sharpes)
        std_wf   = math.sqrt(
            sum((s - mean_wf) ** 2 for s in fold_sharpes) / len(fold_sharpes)
        )
        dd_penalty = 1.0 * max(0.0, max_dd - 15.0) / 100.0
        score = mean_wf - 0.5 * std_wf - dd_penalty

        logger.info(
            "trial %d: fold_sharpes=%s mean_wf=%.3f std_wf=%.3f "
            "max_dd=%.1f dd_penalty=%.3f composite=%.3f",
            trial.number, [round(s, 3) for s in fold_sharpes],
            mean_wf, std_wf, max_dd, dd_penalty, score,
        )

        mean_cagr = sum(fold_cagrs) / len(fold_cagrs)
        trial.set_user_attr("insample_cagr",  round(mean_cagr, 4))
        trial.set_user_attr("wf_sharpe_mean", round(mean_wf,   4))
        trial.set_user_attr("wf_sharpe_std",  round(std_wf,    4))
        for _i, _s in enumerate(fold_sharpes, 1):
            trial.set_user_attr(f"wf_sharpe_f{_i}", round(_s, 4))
        trial.set_user_attr("max_dd_pct",  round(max_dd,    4))
        trial.set_user_attr("dd_penalty",  round(dd_penalty, 4))
        return score

    def _trial_progress_cb(study: optuna.Study, trial: "optuna.trial.FrozenTrial") -> None:
        if progress_callback:
            try:
                progress_callback(len(study.trials), opt_cfg.max_trials, "In-sample search")
            except Exception:  # noqa: BLE001
                pass

    study.optimize(
        _objective,
        n_trials=opt_cfg.max_trials,
        show_progress_bar=True,
        catch=(Exception,),
        callbacks=[_trial_progress_cb],
    )
    if progress_callback:
        progress_callback(
            opt_cfg.max_trials, opt_cfg.max_trials,
            "Validating (walk-forward + overfit checks)",
        )

    best_trial = study.best_trial
    best_composite_score = best_trial.value or 0.0
    best_trial_wf_mean   = best_trial.user_attrs.get("wf_sharpe_mean", 0.0)
    best_trial_wf_std    = best_trial.user_attrs.get("wf_sharpe_std",  0.0)
    best_trial_wf_fold_sharpes = [
        best_trial.user_attrs.get(f"wf_sharpe_f{i}", 0.0)
        for i in range(1, n_cv_folds + 1)
    ]
    best_trial_max_dd_pct = best_trial.user_attrs.get("max_dd_pct",  0.0)
    best_trial_dd_penalty = best_trial.user_attrs.get("dd_penalty",  0.0)
    best_strat, best_bk = build_strat_from_trial(
        best_trial, base_cfg,
        include_scoring_tables=opt_cfg.include_scoring_tables,
        include_sizing=opt_cfg.include_sizing,
    )

    # ── 4. Full in-sample metrics (for report) ────────────────────────────────
    is_result = fast_backtest_with_benchmark(
        precomputed, best_strat, base_cfg, best_bk,
        all_dates[0], insample_end, data_fetcher,
        include_scoring_tables=opt_cfg.include_scoring_tables,
    )

    # Count trials that beat QQQ benchmark on in-sample (using stored user attrs, no re-run)
    qqq_is_cagr = is_result.benchmark_metrics.get("cagr", 0.0)
    n_beat_bm = sum(
        1 for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE
        and t.user_attrs.get("insample_cagr", 0.0) > qqq_is_cagr
    )

    # ── 5. Holdout validation ─────────────────────────────────────────────────
    logger.info("Running holdout validation…")
    holdout_result = fast_backtest_with_benchmark(
        precomputed, best_strat, base_cfg, best_bk,
        holdout_start, all_dates[-1], data_fetcher,
        include_scoring_tables=opt_cfg.include_scoring_tables,
    )

    # SPY comparison on holdout
    spy_bk = best_bk.model_copy(update={"benchmark_symbol": "SPY"})
    from backend.app.backtest.engine import _run_benchmark
    spy_metrics, _ = _run_benchmark(data_fetcher, holdout_start, all_dates[-1], spy_bk)

    # ── 6. Walk-forward ───────────────────────────────────────────────────────
    logger.info("Running walk-forward (%d folds)…", opt_cfg.n_folds)
    wf_result = run_walk_forward(
        precomputed=precomputed,
        full_start=all_dates[0],
        full_end=all_dates[-1],
        base_cfg=base_cfg,
        n_folds=opt_cfg.n_folds,
        max_trials_per_fold=max(50, opt_cfg.max_trials // opt_cfg.n_folds),
        max_drawdown_limit=opt_cfg.max_drawdown_limit,
        include_scoring_tables=opt_cfg.include_scoring_tables,
        include_sizing=opt_cfg.include_sizing,
        seed=opt_cfg.seed,
    )

    # ── 7. Anti-overfitting analysis ──────────────────────────────────────────
    def _calmar(m: dict) -> float:
        cagr = m.get("cagr", 0.0)
        dd   = m.get("max_drawdown", 0.0)
        return cagr / dd if dd > 0 else 0.0

    luck_audit = _run_luck_audit(
        study=study,
        precomputed=precomputed,
        base_cfg=base_cfg,
        holdout_start=holdout_start,
        holdout_end=all_dates[-1],
        holdout_benchmark_sharpe=holdout_result.benchmark_metrics.get("sharpe_ratio", 0.0),
        holdout_benchmark_calmar=_calmar(holdout_result.benchmark_metrics),
        n_random=opt_cfg.n_luck_audit_configs,
        opt_cfg=opt_cfg,
        data_fetcher=data_fetcher,
    )

    perturbation_results = _run_perturbation_test(
        best_params=best_trial.params,
        base_cfg=base_cfg,
        precomputed=precomputed,
        holdout_start=holdout_start,
        holdout_end=all_dates[-1],
        n_nudges=opt_cfg.n_perturbation_nudges,
        opt_cfg=opt_cfg,
        data_fetcher=data_fetcher,
    )

    cluster_analysis = _run_cluster_check(
        study=study,
        top_n=opt_cfg.top_cluster_n,
    )

    # ── 8. Verdict ────────────────────────────────────────────────────────────
    h_m = holdout_result.metrics
    h_bm = holdout_result.benchmark_metrics
    wf_m = wf_result.oos_metrics

    verdict_notes: list[str] = []

    wf_sharpe  = wf_m.get("sharpe_ratio", 0.0)
    wf_calmar  = _calmar(wf_m)
    wf_dd      = wf_m.get("max_drawdown", 100.0)
    qqq_sharpe = h_bm.get("sharpe_ratio", 0.0)
    qqq_calmar = _calmar(h_bm)

    is_sharpe  = is_result.metrics.get("sharpe_ratio", 0.0)
    oos_sharpe = h_m.get("sharpe_ratio", 0.0)
    is_oos_gap = is_sharpe - oos_sharpe

    beats_sharpe = wf_sharpe > qqq_sharpe
    beats_calmar = wf_calmar > qqq_calmar
    dd_ok        = wf_dd <= 15.0
    gap_ok       = is_oos_gap <= 0.5

    # Classify into three tiers
    if beats_sharpe and beats_calmar and dd_ok and gap_ok:
        verdict_tier = "ROBUST"
    elif beats_sharpe or beats_calmar:
        verdict_tier = "SUSPECT"
    else:
        verdict_tier = "OVERFIT"

    # IS→OOS gap override: even a partial win is flagged OVERFIT if gap is too large
    if not gap_ok:
        verdict_tier = "OVERFIT"
        verdict_notes.append(
            f"OVERFIT SIGNAL: IS Sharpe ({is_sharpe:.2f}) − OOS Sharpe ({oos_sharpe:.2f}) "
            f"= {is_oos_gap:.2f} > 0.50 threshold"
        )

    if verdict_tier == "ROBUST":
        verdict_notes.append(
            f"ROBUST: Walk-forward Sharpe ({wf_sharpe:.2f} > QQQ {qqq_sharpe:.2f}), "
            f"Calmar ({wf_calmar:.2f} > QQQ {qqq_calmar:.2f}), DD {wf_dd:.1f}% ≤ 15%, "
            f"IS–OOS gap {is_oos_gap:.2f} ≤ 0.50."
        )
        if opt_cfg.include_scoring_tables:
            verdict_notes.append(
                "WARNING: Aggressive search with scoring tables active — treat as SUSPECTED "
                "OVERFIT until confirmed by live paper-trading."
            )
    elif verdict_tier == "SUSPECT":
        beaten = []
        if beats_sharpe: beaten.append(f"Sharpe ({wf_sharpe:.2f} > QQQ {qqq_sharpe:.2f})")
        if beats_calmar: beaten.append(f"Calmar ({wf_calmar:.2f} > QQQ {qqq_calmar:.2f})")
        missed = []
        if not beats_sharpe: missed.append(f"Sharpe ({wf_sharpe:.2f} ≤ QQQ {qqq_sharpe:.2f})")
        if not beats_calmar: missed.append(f"Calmar ({wf_calmar:.2f} ≤ QQQ {qqq_calmar:.2f})")
        if not dd_ok: missed.append(f"DD {wf_dd:.1f}% > 15%")
        verdict_notes.append(
            f"SUSPECT: Beats QQQ on {', '.join(beaten)} but not on {', '.join(missed)}."
        )
    else:
        if not beats_sharpe:
            verdict_notes.append(
                f"FAIL: Walk-forward Sharpe ({wf_sharpe:.2f}) ≤ QQQ ({qqq_sharpe:.2f})"
            )
        if not beats_calmar:
            verdict_notes.append(
                f"FAIL: Walk-forward Calmar ({wf_calmar:.2f}) ≤ QQQ ({qqq_calmar:.2f})"
            )
        if not dd_ok:
            verdict_notes.append(
                f"FAIL: Walk-forward max drawdown ({wf_dd:.1f}%) > 15% limit"
            )

    pass_verdict = verdict_tier == "ROBUST"

    wall_clock = time.perf_counter() - t0
    logger.info("Optimisation complete in %.1f s. Verdict: %s", wall_clock,
                "PASS" if pass_verdict else "FAIL")

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

    # Build per-trial records for CSV export
    trial_records: list[dict] = []
    for t in completed:
        if t.value is None:
            continue
        w = weights_from_params(t.params)
        trial_records.append({
            "trial_number":    t.number,
            "composite_score": round(t.value, 6),
            "wf_sharpe_mean":  t.user_attrs.get("wf_sharpe_mean", 0.0),
            "wf_sharpe_std":   t.user_attrs.get("wf_sharpe_std",  0.0),
            **{f"wf_sharpe_f{i}": t.user_attrs.get(f"wf_sharpe_f{i}", 0.0)
               for i in range(1, n_cv_folds + 1)},
            "max_dd_pct":      t.user_attrs.get("max_dd_pct",  0.0),
            "dd_penalty":      t.user_attrs.get("dd_penalty",  0.0),
            **{name: round(val, 4) for name, val in w.items()},
            "entry_threshold": t.params.get("entry_threshold", 0.0),
            "exit_threshold":  t.params.get("exit_threshold",  0.0),
        })

    return OptimisationResult(
        best_params=best_trial.params,
        best_strat_dict=best_strat.model_dump(),
        insample_metrics=is_result.metrics,
        holdout_metrics=holdout_result.metrics,
        holdout_benchmark_metrics=h_bm,
        benchmark_vs_spy_metrics=spy_metrics,
        wf_metrics=wf_m,
        wf_folds=wf_result.folds,
        luck_audit=luck_audit,
        perturbation_results=perturbation_results,
        cluster_analysis=cluster_analysis,
        insample_start=all_dates[0],
        insample_end=insample_end,
        holdout_start=holdout_start,
        holdout_end=all_dates[-1],
        wall_clock_seconds=wall_clock,
        n_trials_attempted=len(completed),
        n_trials_in_sample_beat_benchmark=n_beat_bm,
        pass_verdict=pass_verdict,
        verdict_tier=verdict_tier,
        verdict_notes=verdict_notes,
        best_composite_score=best_composite_score,
        best_trial_wf_mean=best_trial_wf_mean,
        best_trial_wf_std=best_trial_wf_std,
        best_trial_wf_fold_sharpes=best_trial_wf_fold_sharpes,
        best_trial_max_dd_pct=best_trial_max_dd_pct,
        best_trial_dd_penalty=best_trial_dd_penalty,
        trial_records=trial_records,
    )


# ── Anti-overfitting helpers ───────────────────────────────────────────────────

def _run_luck_audit(
    study: optuna.Study,
    precomputed: dict,
    base_cfg: AppConfig,
    holdout_start: date,
    holdout_end: date,
    holdout_benchmark_sharpe: float,
    holdout_benchmark_calmar: float,
    n_random: int,
    opt_cfg: OptimiserConfig,
    data_fetcher: Callable,
) -> dict:
    """Count how many of the top completed trials beat benchmark on holdout.

    Win criterion: beats QQQ on BOTH Sharpe AND Calmar (risk-adjusted).
    Also runs n_random completely random configs through the holdout to estimate
    the chance baseline (how many random configs "win" by luck alone).
    """
    logger.info("Running luck audit (%d random null configs)…", n_random)

    def _is_winner(m: dict) -> bool:
        strat_sharpe = m.get("sharpe_ratio", 0.0)
        strat_cagr   = m.get("cagr", 0.0)
        strat_dd     = m.get("max_drawdown", 0.0)
        strat_calmar = strat_cagr / strat_dd if strat_dd > 0 else 0.0
        return strat_sharpe > holdout_benchmark_sharpe and strat_calmar > holdout_benchmark_calmar

    completed = [
        t for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]
    n_total = len(completed)

    # Sample the top 200 (by composite objective score) to evaluate on holdout
    top_trials = sorted(completed, key=lambda t: t.value or 0.0, reverse=True)[:200]
    n_holdout_winners = 0
    for t in top_trials:
        try:
            strat, bk = build_strat_from_trial(
                t, base_cfg,
                include_scoring_tables=opt_cfg.include_scoring_tables,
                include_sizing=opt_cfg.include_sizing,
            )
            res = fast_backtest_long(
                precomputed, strat, base_cfg, bk, holdout_start, holdout_end,
                include_scoring_tables=opt_cfg.include_scoring_tables,
            )
            if _is_winner(res.metrics):
                n_holdout_winners += 1
        except Exception:  # noqa: BLE001
            pass

    # Null/random baseline: create random configs and count holdout "wins"
    rng = random.Random(opt_cfg.seed + 9999)
    null_study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.RandomSampler(seed=opt_cfg.seed + 9999),
    )
    null_wins = 0
    for _ in range(n_random):
        trial = null_study.ask()
        try:
            strat, bk = build_strat_from_trial(
                trial, base_cfg,
                include_scoring_tables=opt_cfg.include_scoring_tables,
                include_sizing=opt_cfg.include_sizing,
            )
            res = fast_backtest_long(
                precomputed, strat, base_cfg, bk, holdout_start, holdout_end,
                include_scoring_tables=opt_cfg.include_scoring_tables,
            )
            if _is_winner(res.metrics):
                null_wins += 1
            null_study.tell(trial, res.metrics.get("sharpe_ratio", 0.0))
        except Exception:  # noqa: BLE001
            null_study.tell(trial, 0.0)

    null_win_rate = null_wins / n_random if n_random else 0.0
    observed_win_rate = n_holdout_winners / len(top_trials) if top_trials else 0.0
    likely_noise = abs(observed_win_rate - null_win_rate) < 0.10

    return {
        "n_completed_trials": n_total,
        "top_200_evaluated_on_holdout": len(top_trials),
        "n_holdout_winners": n_holdout_winners,
        "holdout_win_rate": round(observed_win_rate, 3),
        "null_trials": n_random,
        "null_holdout_wins": null_wins,
        "null_win_rate": round(null_win_rate, 3),
        "likely_noise": likely_noise,
        "win_criterion": "beats QQQ on Sharpe AND Calmar (risk-adjusted)",
        "assessment": (
            "⚠ Winner is likely NOISE: observed win rate is close to random baseline."
            if likely_noise
            else "Observed holdout win rate exceeds random baseline — some real edge possible."
        ),
    }


def _run_perturbation_test(
    best_params: dict,
    base_cfg: AppConfig,
    precomputed: dict,
    holdout_start: date,
    holdout_end: date,
    n_nudges: int,
    opt_cfg: OptimiserConfig,
    data_fetcher: Callable,
) -> list[dict]:
    """Nudge one of the best config's component scores ±10 points and measure
    holdout stability. A REAL edge degrades gracefully; an OVERFIT config collapses.
    """
    logger.info("Running perturbation test (%d nudges)…", n_nudges)
    rng = random.Random(opt_cfg.seed + 777)
    weight_keys = list(ENTRY_PARAM.values()) + list(EXIT_PARAM.values())

    results: list[dict] = []

    class _MockTrial:
        def __init__(self, params):
            self._params = params
        def suggest_float(self, name, low, high):
            v = self._params.get(name, (low + high) / 2)
            return max(low, min(high, float(v)))
        def suggest_int(self, name, low, high):
            v = self._params.get(name, (low + high) // 2)
            return max(low, min(high, int(v)))
        @property
        def params(self):
            return self._params

    for nudge_idx in range(n_nudges):
        mock_params = dict(best_params)
        key = rng.choice(weight_keys)
        shift = rng.uniform(-10.0, 10.0)
        mock_params[key] = max(0.0, float(mock_params.get(key, 0.0)) + shift)

        try:
            strat, bk = build_strat_from_trial(
                _MockTrial(mock_params), base_cfg,
                include_scoring_tables=opt_cfg.include_scoring_tables,
                include_sizing=opt_cfg.include_sizing,
            )
            res = fast_backtest_long(
                precomputed, strat, base_cfg, bk, holdout_start, holdout_end,
            )
            results.append({
                "nudge": nudge_idx + 1,
                "param": key, "shift": round(shift, 1),
                "sharpe": res.metrics.get("sharpe_ratio", 0.0),
                "cagr":   res.metrics.get("cagr", 0.0),
                "max_dd": res.metrics.get("max_drawdown", 0.0),
            })
        except Exception:  # noqa: BLE001
            results.append({"nudge": nudge_idx + 1, "error": True})

    return results


def _run_cluster_check(study: optuna.Study, top_n: int) -> dict:
    """Check whether the top N in-sample configs have CLUSTERED or SCATTERED weights.

    Clustered weights → a real region of parameter space with an edge.
    Scattered weights → winners are random draws.
    """
    _WEIGHT_NAMES = ENTRY_WEIGHTS + EXIT_WEIGHTS
    completed = [
        t for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]
    top = sorted(completed, key=lambda t: t.value or 0.0, reverse=True)[:top_n]
    if len(top) < 5:
        return {"assessment": "Too few trials for cluster analysis."}

    # Extract raw entry/exit weights for each top trial
    weight_matrix = []
    for t in top:
        w = weights_from_params(t.params)
        weight_matrix.append([w[n] for n in _WEIGHT_NAMES])

    # Compute pairwise Euclidean distances and average
    import itertools
    dists = []
    for a, b in itertools.combinations(weight_matrix, 2):
        d = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
        dists.append(d)

    avg_dist = sum(dists) / len(dists) if dists else 0.0
    max_possible = math.sqrt(8) * 100.0  # theoretical max for 8 weights in [0,100]
    # Heuristic: if avg distance < 25 points, we call it "clustered"
    is_clustered = avg_dist < 25.0

    # Component means and std for top configs
    component_means = {}
    component_stds  = {}
    for i, n in enumerate(_WEIGHT_NAMES):
        vals = [row[i] for row in weight_matrix]
        mean = sum(vals) / len(vals)
        std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        component_means[n] = round(mean, 1)
        component_stds[n]  = round(std, 1)

    return {
        "n_top_configs": len(top),
        "avg_pairwise_distance": round(avg_dist, 1),
        "is_clustered": is_clustered,
        "component_means": component_means,
        "component_stds": component_stds,
        "assessment": (
            f"CLUSTERED (avg weight distance {avg_dist:.1f} points < 25) — "
            "top configs agree on similar weights, suggesting a real region of edge."
            if is_clustered
            else f"SCATTERED (avg weight distance {avg_dist:.1f} points ≥ 25) — "
            "top configs do NOT agree on weights; winners may be random draws."
        ),
    }


# ── Candidate config persistence ──────────────────────────────────────────────

def save_candidate_config(
    opt_result: OptimisationResult,
    strategy: str,
    base_cfg: AppConfig,
    output_path: Path | None = None,
) -> Path:
    """Write the best config as config.candidate.<strategy>.yaml (never overwrites live config)."""
    if output_path is None:
        output_path = _REPO_ROOT / f"config.candidate.{strategy}.yaml"

    # Load the live config as a baseline dict
    live_path = _REPO_ROOT / "config.yaml"
    with open(live_path) as fh:
        live_dict = yaml.safe_load(fh)

    # Replace strategy-specific section with optimised values. best_strat_dict
    # uses descriptive field names (for the report/printout); re-dump it with the
    # Pine alias keys so the candidate file stays 1:1 with the live config.yaml
    # schema and can be promoted with a plain copy.
    live_dict["strategies"][strategy] = (
        StrategyConfig.model_validate(opt_result.best_strat_dict).model_dump(by_alias=True)
    )

    with open(output_path, "w") as fh:
        yaml.dump(live_dict, fh, default_flow_style=False, sort_keys=False)

    logger.info("Candidate config saved to %s", output_path)
    return output_path

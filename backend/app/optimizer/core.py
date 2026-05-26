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

from backend.app.config import AppConfig, BacktestConfig
from backend.app.optimizer.fast_engine import fast_backtest_long, fast_backtest_with_benchmark
from backend.app.optimizer.param_space import (
    build_strat_from_trial,
    extract_weights_from_params,
    weights_sum_to_100,
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
    strategy: Literal["long"] = "long"
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
    verdict_notes: list[str] = field(default_factory=list)


# ── Public entry point ─────────────────────────────────────────────────────────

def run_optimisation(
    symbols: list[str],
    start: date,
    end: date,
    base_cfg: AppConfig,
    data_fetcher: Callable,
    opt_cfg: OptimiserConfig | None = None,
) -> OptimisationResult:
    """Full optimisation pipeline. Returns OptimisationResult with all findings."""
    if opt_cfg is None:
        opt_cfg = OptimiserConfig()

    t0 = time.perf_counter()

    # ── 1. Pre-compute ────────────────────────────────────────────────────────
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

    def _objective(trial: optuna.Trial) -> float:
        strat, bk = build_strat_from_trial(
            trial, base_cfg,
            include_scoring_tables=opt_cfg.include_scoring_tables,
            include_sizing=opt_cfg.include_sizing,
        )
        # CRITICAL: objective only sees in-sample data
        res = fast_backtest_long(
            precomputed, strat, base_cfg, bk,
            all_dates[0], insample_end,
            include_scoring_tables=opt_cfg.include_scoring_tables,
        )
        m = res.metrics
        dd = m.get("max_drawdown", 100.0)
        if dd > opt_cfg.max_drawdown_limit * 100:
            raise optuna.exceptions.TrialPruned()
        # Store CAGR as a user attribute so luck audit can count without re-running
        trial.set_user_attr("insample_cagr", m.get("cagr", 0.0))
        return m.get("sharpe_ratio", 0.0)

    study.optimize(
        _objective,
        n_trials=opt_cfg.max_trials,
        show_progress_bar=True,
        catch=(Exception,),
    )

    best_trial = study.best_trial
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
    luck_audit = _run_luck_audit(
        study=study,
        precomputed=precomputed,
        base_cfg=base_cfg,
        holdout_start=holdout_start,
        holdout_end=all_dates[-1],
        holdout_benchmark_cagr=holdout_result.benchmark_metrics.get("cagr", 0.0),
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
    holdout_beats_qqq = h_m.get("cagr", 0.0) > h_bm.get("cagr", 0.0)
    holdout_dd_ok     = h_m.get("max_drawdown", 100.0) <= opt_cfg.max_drawdown_limit * 100
    wf_beats_qqq      = wf_m.get("cagr", 0.0) > is_result.benchmark_metrics.get("cagr", 0.0)
    wf_dd_ok          = wf_m.get("max_drawdown", 100.0) <= opt_cfg.max_drawdown_limit * 100

    pass_verdict = holdout_beats_qqq and holdout_dd_ok and wf_beats_qqq and wf_dd_ok

    if not holdout_beats_qqq:
        verdict_notes.append(
            f"FAIL: Holdout CAGR ({h_m.get('cagr', 0):.1f}%) does not beat QQQ "
            f"({h_bm.get('cagr', 0):.1f}%)"
        )
    if not holdout_dd_ok:
        verdict_notes.append(
            f"FAIL: Holdout max drawdown ({h_m.get('max_drawdown', 0):.1f}%) "
            f"exceeds limit ({opt_cfg.max_drawdown_limit*100:.0f}%)"
        )
    if not wf_beats_qqq:
        verdict_notes.append(
            f"FAIL: Walk-forward OOS CAGR ({wf_m.get('cagr', 0):.1f}%) does not beat QQQ"
        )
    if not wf_dd_ok:
        verdict_notes.append(
            f"FAIL: Walk-forward OOS max drawdown ({wf_m.get('max_drawdown', 0):.1f}%) "
            f"exceeds limit"
        )
    if pass_verdict:
        verdict_notes.append(
            "PASS: Beats QQQ on holdout AND walk-forward, within drawdown limit."
        )
        if opt_cfg.include_scoring_tables:
            verdict_notes.append(
                "WARNING: Aggressive search with scoring tables active — treat as SUSPECTED "
                "OVERFIT until confirmed by live paper-trading."
            )

    wall_clock = time.perf_counter() - t0
    logger.info("Optimisation complete in %.1f s. Verdict: %s", wall_clock,
                "PASS" if pass_verdict else "FAIL")

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

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
        verdict_notes=verdict_notes,
    )


# ── Anti-overfitting helpers ───────────────────────────────────────────────────

def _run_luck_audit(
    study: optuna.Study,
    precomputed: dict,
    base_cfg: AppConfig,
    holdout_start: date,
    holdout_end: date,
    holdout_benchmark_cagr: float,
    n_random: int,
    opt_cfg: OptimiserConfig,
    data_fetcher: Callable,
) -> dict:
    """Count how many of the top completed trials beat benchmark on holdout.

    Also runs n_random completely random configs through the holdout to estimate
    the chance baseline (how many random configs "win" by luck alone).
    """
    logger.info("Running luck audit (%d random null configs)…", n_random)

    completed = [
        t for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]
    n_total = len(completed)

    # Sample the top 200 (by in-sample Sharpe) to evaluate on holdout
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
            if res.metrics.get("cagr", 0.0) > holdout_benchmark_cagr:
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
            if res.metrics.get("cagr", 0.0) > holdout_benchmark_cagr:
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
    """Nudge the best config's weights ±5-10 points and measure holdout stability.

    A REAL edge degrades gracefully; an OVERFIT config collapses.
    """
    logger.info("Running perturbation test (%d nudges)…", n_nudges)
    rng = random.Random(opt_cfg.seed + 777)
    _WEIGHT_NAMES = ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]

    # Reconstruct best normalised weights
    raw_best = {n: best_params.get(f"w_{n}", 1.0) for n in _WEIGHT_NAMES}
    total = sum(raw_best.values())
    best_normalised = {n: v / total * 100.0 for n, v in raw_best.items()}

    results: list[dict] = []

    for nudge_idx in range(n_nudges):
        # Randomly redistribute 5-10 points among weight pairs
        nudge_w = dict(best_normalised)
        donor = rng.choice(_WEIGHT_NAMES)
        recipient = rng.choice([n for n in _WEIGHT_NAMES if n != donor])
        shift = rng.uniform(5.0, 10.0)
        nudge_w[donor]    = max(0.5, nudge_w[donor] - shift)
        nudge_w[recipient] = nudge_w[recipient] + shift
        # Re-normalise
        total_n = sum(nudge_w.values())
        nudge_w = {k: v / total_n * 100.0 for k, v in nudge_w.items()}

        # Build a mock trial-like object to reuse build_strat_from_trial
        mock_params = dict(best_params)
        for n in _WEIGHT_NAMES:
            mock_params[f"w_{n}"] = nudge_w[n]  # store already-normalised as raw

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

        try:
            strat, bk = build_strat_from_trial(
                _MockTrial(mock_params), base_cfg,
                include_scoring_tables=opt_cfg.include_scoring_tables,
                include_sizing=opt_cfg.include_sizing,
            )
            res = fast_backtest_long(
                precomputed, strat, base_cfg, bk, holdout_start, holdout_end,
                include_scoring_tables=opt_cfg.include_scoring_tables,
            )
            results.append({
                "nudge": nudge_idx + 1,
                "donor": donor, "recipient": recipient, "shift": round(shift, 1),
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
    _WEIGHT_NAMES = ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"]
    completed = [
        t for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
    ]
    top = sorted(completed, key=lambda t: t.value or 0.0, reverse=True)[:top_n]
    if len(top) < 5:
        return {"assessment": "Too few trials for cluster analysis."}

    # Extract normalised weights for each top trial
    weight_matrix = []
    for t in top:
        raw = {n: t.params.get(f"w_{n}", 1.0) for n in _WEIGHT_NAMES}
        total = sum(raw.values())
        norm = [raw[n] / total * 100.0 for n in _WEIGHT_NAMES]
        weight_matrix.append(norm)

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

    # Replace strategy-specific section with optimised values
    live_dict["strategies"][strategy] = opt_result.best_strat_dict

    with open(output_path, "w") as fh:
        yaml.dump(live_dict, fh, default_flow_style=False, sort_keys=False)

    logger.info("Candidate config saved to %s", output_path)
    return output_path

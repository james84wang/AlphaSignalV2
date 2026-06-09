#!/usr/bin/env python
"""MOD-I: Strategy optimiser with overfitting protection.

Optimises the hidden_div (Hidden-Divergence Confluence) strategy using Bayesian
search (Optuna/TPE) on a 70% in-sample window, validates on the held-out 30%,
runs walk-forward validation over 4 folds, and writes a markdown report with a
clear PASS/FAIL verdict.

The live config.yaml is NEVER touched; the winner is saved to
config.candidate.<strategy>.yaml for manual review and promotion.

Usage examples:
  # Optimise over the default 5-year window (watchlist universe)
  uv run python scripts/optimize.py

  # Full combined universe (slower)
  uv run python scripts/optimize.py --universe combined

  # A single named watchlist
  uv run python scripts/optimize.py --universe "wl:Watchlist - ChinaTech"

  # With custom date range
  uv run python scripts/optimize.py --start 2020-01-01 --end 2025-01-01

  # Aggressive Phase-2 (also tunes the confluence windows)
  uv run python scripts/optimize.py --include-scoring-tables

  # Include position sizing in search (Phase-3)
  uv run python scripts/optimize.py --include-sizing

  # Quick test (few trials)
  uv run python scripts/optimize.py --trials 50 --universe watchlist
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.config import load_config, reset_config
from backend.app.data.cache import ParquetCache
from backend.app.data.watchlists import resolve_universe
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.optimizer.core import OptimiserConfig, run_optimisation, save_candidate_config
from backend.app.optimizer.report import generate_report, write_trials_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_symbols(universe: str, cfg) -> list[str]:
    """Resolve a universe id (watchlist | wl:<name> | sp500 | … | combined)."""
    syms = resolve_universe(universe, cfg)
    if not syms and universe == "watchlist":
        # Convenience fallback when the watchlist DB is empty.
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
                "JPM", "V", "UNH", "MA", "HD", "PG", "BAC", "XOM"]
    return syms


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AlphaSignalV2 Strategy Optimiser (MOD-I)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--strategy", choices=["hidden_div"], default="hidden_div")
    parser.add_argument("--universe", default="watchlist",
                        help="watchlist | wl:<name> | sp500 | midcap | smallcap | nasdaq100 | combined")
    parser.add_argument("--start", type=str, default=None,
                        help="Start date YYYY-MM-DD (default: 5 years back)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--trials", type=int, default=2000,
                        help="Max Optuna trials for in-sample search (default 2000)")
    parser.add_argument("--folds", type=int, default=4,
                        help="Walk-forward folds (default 4)")
    parser.add_argument("--insample-ratio", type=float, default=0.70,
                        help="Fraction of data used for in-sample (default 0.70)")
    parser.add_argument("--max-drawdown-limit", type=float, default=0.25,
                        help="Hard drawdown constraint 0–1 (default 0.25 = 25%%)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-scoring-tables", action="store_true",
                        help="Phase-2: also optimise scoring table multipliers (higher overfit risk)")
    parser.add_argument("--include-sizing", action="store_true",
                        help="Phase-3: also optimise position sizing and concurrent limits")
    args = parser.parse_args()

    # ── Config + date range ───────────────────────────────────────────────────
    reset_config()
    cfg = load_config()

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = (
        date.fromisoformat(args.start)
        if args.start
        else end - timedelta(days=cfg.backtest.start_years_back * 365)
    )

    # ── Universe ──────────────────────────────────────────────────────────────
    logger.info("Loading universe: %s", args.universe)
    symbols = _load_symbols(args.universe, cfg)
    logger.info("Universe size: %d symbols", len(symbols))

    # ── Data fetcher ──────────────────────────────────────────────────────────
    provider = YFinanceProvider()
    cache    = ParquetCache(provider)
    def _fetcher(sym: str, s: date, e: date):
        return cache.get_daily_bars(sym, s, e)

    # ── Optimiser config ──────────────────────────────────────────────────────
    opt_cfg = OptimiserConfig(
        strategy=args.strategy,
        years=cfg.backtest.start_years_back,
        insample_ratio=args.insample_ratio,
        max_trials=args.trials,
        n_folds=args.folds,
        max_drawdown_limit=args.max_drawdown_limit,
        seed=args.seed,
        include_scoring_tables=args.include_scoring_tables,
        include_sizing=args.include_sizing,
    )

    logger.info(
        "Starting optimisation: strategy=%s, %d trials, %d WF folds, seed=%d",
        args.strategy, opt_cfg.max_trials, opt_cfg.n_folds, opt_cfg.seed,
    )
    logger.info("Date range: %s → %s", start, end)
    logger.info(
        "Phases active: weights+thresholds=YES, scoring_tables=%s, sizing=%s",
        "YES" if opt_cfg.include_scoring_tables else "NO",
        "YES" if opt_cfg.include_sizing else "NO",
    )

    # ── Run ───────────────────────────────────────────────────────────────────
    result = run_optimisation(
        symbols=symbols,
        start=start,
        end=end,
        base_cfg=cfg,
        data_fetcher=_fetcher,
        opt_cfg=opt_cfg,
    )

    # ── Save candidate config ─────────────────────────────────────────────────
    candidate_path = save_candidate_config(result, args.strategy, cfg)

    # ── Write report + per-trial CSV ─────────────────────────────────────────
    report_path = generate_report(result, args.strategy, symbols,
                                  candidate_path=candidate_path)
    logger.info("Report written to %s", report_path)
    csv_path = write_trials_csv(result, args.strategy)
    logger.info("Trials CSV written to %s (%d rows)", csv_path, len(result.trial_records))

    # ── Summary printout ──────────────────────────────────────────────────────
    is_m = result.insample_metrics
    h_m  = result.holdout_metrics
    h_bm = result.holdout_benchmark_metrics
    wf_m = result.wf_metrics

    w = 66
    print(f"\n{'═'*w}")
    print("  MOD-I OPTIMISATION RESULT — AlphaSignalV2")
    print(f"{'═'*w}")
    print(f"  Strategy : {args.strategy}")
    print(f"  Universe : {len(symbols)} symbols")
    print(f"  Period   : {start} → {end}")
    print(f"  In-sample: {result.insample_start} → {result.insample_end}")
    print(f"  Holdout  : {result.holdout_start} → {result.holdout_end}")
    print(f"  Trials   : {result.n_trials_attempted} completed")
    print(f"  Wall clock: {result.wall_clock_seconds/60:.1f} min")
    print(f"{'─'*w}")
    print(f"  {'Metric':<22} {'In-Sample':>12} {'Holdout':>12} {'Walk-Fwd OOS':>14}")
    print(f"  {'─'*22} {'─'*12} {'─'*12} {'─'*14}")

    def _pr(label, key, fmt="pct"):
        iv = is_m.get(key, 0.0)
        hv = h_m.get(key, 0.0)
        wv = wf_m.get(key, 0.0)
        if fmt == "pct":
            print(f"  {label:<22} {iv:>+11.1f}% {hv:>+11.1f}% {wv:>+13.1f}%")
        else:
            print(f"  {label:<22} {iv:>12.3f} {hv:>12.3f} {wv:>13.3f}")

    _pr("CAGR", "cagr")
    _pr("Total return", "total_return")
    _pr("Sharpe ratio", "sharpe_ratio", "f")
    _pr("Max drawdown", "max_drawdown")

    print(f"{'─'*w}")
    print(f"  QQQ holdout CAGR : {h_bm.get('cagr', 0.0):+.1f}%")
    print(f"  Beats QQQ holdout: {'YES' if h_m.get('cagr', 0) > h_bm.get('cagr', 0) else 'NO'}")
    print(f"{'─'*w}")

    # Verdict
    verdict_str = "✅  PASS" if result.pass_verdict else "❌  FAIL"
    print(f"\n  VERDICT: {verdict_str}")
    for note in result.verdict_notes:
        print(f"  • {note}")

    # Overfitting assessment
    print(f"\n  ── Anti-Overfitting ────────────────────────────────────")
    la = result.luck_audit
    print(f"  Luck audit: {la.get('n_holdout_winners',0)}/{la.get('top_200_evaluated_on_holdout',0)} "
          f"top configs beat QQQ on holdout "
          f"(random baseline: {la.get('null_holdout_wins',0)}/{la.get('null_trials',0)})")
    print(f"  {la.get('assessment','')}")

    cl = result.cluster_analysis
    print(f"  Cluster check: {cl.get('assessment','')[:80]}")

    pert = [p for p in result.perturbation_results if "error" not in p]
    if pert:
        mean_s = sum(p["sharpe"] for p in pert) / len(pert)
        print(f"  Perturbation: {len(pert)} nudges, mean holdout Sharpe after nudge = {mean_s:.3f} "
              f"(best config holdout Sharpe = {h_m.get('sharpe_ratio', 0):.3f})")

    entry_cfg = result.best_strat_dict.get("entry", {})
    exit_cfg = result.best_strat_dict.get("exit", {})
    print(f"\n  Best entry scores (Buy ≥ {entry_cfg.get('threshold', 0):.0f}, "
          f"window {entry_cfg.get('conf_window', 0)}):")
    for comp, wval in entry_cfg.get("weights", {}).items():
        print(f"    {comp:<20}: {wval:.1f}")
    print(f"  Best exit scores (Sell ≥ {exit_cfg.get('threshold', 0):.0f}, "
          f"window {exit_cfg.get('conf_window', 0)}):")
    for comp, wval in exit_cfg.get("weights", {}).items():
        print(f"    {comp:<20}: {wval:.1f}")

    print(f"\n  Candidate config: {candidate_path}")
    print(f"  Report          : {report_path}")
    print(f"  Trials CSV      : {csv_path}  ({len(result.trial_records)} rows)")
    print(f"\n{'═'*w}\n")

    # ── How to promote ────────────────────────────────────────────────────────
    print("  ─── HOW TO PROMOTE A CANDIDATE CONFIG ──────────────────")
    print("  1. Review the report above and verify it passes your criteria.")
    print(f"  2. Inspect the candidate file: cat {candidate_path.name}")
    print(f"  3. Copy to live config:  cp {candidate_path.name} config.yaml")
    print("  4. Restart backend:      scripts/launch.sh --no-build")
    print()
    print("  ─── HOW TO RE-RUN ──────────────────────────────────────")
    print("  Default (watchlist universe):")
    print("    uv run python scripts/optimize.py --universe watchlist")
    print("  Also tune the confluence windows (aggressive, higher overfit risk):")
    print("    uv run python scripts/optimize.py --include-scoring-tables")
    print()


if __name__ == "__main__":
    main()

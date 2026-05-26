"""Generate a human-readable Markdown optimisation report."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.optimizer.core import OptimisationResult

_REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


def _pct(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:+.{decimals}f}%"


def _f(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def generate_report(
    opt_result: "OptimisationResult",
    strategy: str,
    symbols: list[str],
    report_date: date | None = None,
    candidate_path: Path | None = None,
) -> Path:
    """Write the optimisation report to reports/optimize_<strategy>_<date>.md."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if report_date is None:
        report_date = date.today()
    out = _REPORTS_DIR / f"optimize_{strategy}_{report_date}.md"

    r = opt_result
    is_m  = r.insample_metrics
    h_m   = r.holdout_metrics
    h_bm  = r.holdout_benchmark_metrics
    wf_m  = r.wf_metrics

    lines: list[str] = []

    def h1(s): lines.append(f"# {s}\n")
    def h2(s): lines.append(f"\n## {s}\n")
    def h3(s): lines.append(f"\n### {s}\n")
    def p(s=""):  lines.append(s)

    h1(f"Optimisation Report — {strategy.capitalize()} Strategy — {report_date}")
    p(f"*Generated {report_date} · AlphaSignalV2 MOD-I*")

    h2("Summary")
    p(f"- **Universe**: {len(symbols)} symbols")
    p(f"- **Full period**: {r.insample_start} → {r.holdout_end}")
    p(f"- **In-sample** (70%): {r.insample_start} → {r.insample_end}")
    p(f"- **Holdout** (30%): {r.holdout_start} → {r.holdout_end}")
    p(f"- **Trials completed**: {r.n_trials_attempted}")
    p(f"- **Wall clock**: {r.wall_clock_seconds/60:.1f} min")
    p(f"- **Best in-sample Sharpe**: {_f(is_m.get('sharpe_ratio'))}")
    p()

    # PASS / FAIL verdict
    verdict_str = "✅ PASS" if r.pass_verdict else "❌ FAIL"
    h2(f"Verdict: {verdict_str}")
    for note in r.verdict_notes:
        p(f"- {note}")

    h2("In-Sample vs Holdout vs Walk-Forward")
    p("| Metric | In-Sample | Holdout | Walk-Forward OOS |")
    p("|--------|-----------|---------|-----------------|")

    def _row(label, key, fmt="pct"):
        is_v  = is_m.get(key)
        h_v   = h_m.get(key)
        wf_v  = wf_m.get(key)
        if fmt == "pct":
            p(f"| {label} | {_pct(is_v)} | {_pct(h_v)} | {_pct(wf_v)} |")
        else:
            p(f"| {label} | {_f(is_v)} | {_f(h_v)} | {_f(wf_v)} |")

    _row("CAGR", "cagr")
    _row("Sharpe ratio", "sharpe_ratio", "f")
    _row("Max drawdown", "max_drawdown")
    _row("Total return", "total_return")
    _row("Win rate", "win_rate", "f")
    _row("Profit factor", "profit_factor", "f")
    p()

    # Benchmark comparison
    h2("Benchmark Comparison (Holdout)")
    p("| Metric | Strategy | QQQ | SPY | Beats QQQ? |")
    p("|--------|----------|-----|-----|-----------|")

    def _bm_row(label, key):
        sv = h_m.get(key)
        qv = h_bm.get(key)
        sv2 = r.benchmark_vs_spy_metrics.get(key)
        beats = "✅" if (sv or 0.0) > (qv or 0.0) else "❌"
        if key in ("cagr", "total_return", "max_drawdown"):
            p(f"| {label} | {_pct(sv)} | {_pct(qv)} | {_pct(sv2)} | {beats} |")
        else:
            p(f"| {label} | {_f(sv)} | {_f(qv)} | {_f(sv2)} | {beats} |")

    _bm_row("CAGR", "cagr")
    _bm_row("Sharpe", "sharpe_ratio")
    _bm_row("Max drawdown", "max_drawdown")
    _bm_row("Total return", "total_return")

    # Degradation warning
    is_sharpe = is_m.get("sharpe_ratio", 0.0)
    h_sharpe  = h_m.get("sharpe_ratio", 0.0)
    if is_sharpe > 0 and (h_sharpe / is_sharpe) < 0.60:
        p()
        p(f"> ⚠ **LARGE IN-SAMPLE→HOLDOUT DEGRADATION**: Sharpe dropped from "
          f"{_f(is_sharpe)} to {_f(h_sharpe)} ({(h_sharpe/is_sharpe*100):.0f}% of "
          f"in-sample). This is a strong sign of overfitting.")

    # Best weights
    h2("Best Config — Weights")
    best_w = r.best_strat_dict.get("weights", {})
    sorted_w = sorted(best_w.items(), key=lambda x: x[1], reverse=True)
    p("| Component | Weight |")
    p("|-----------|--------|")
    for name, w in sorted_w:
        p(f"| {name} | {w:.1f}% |")

    # Best thresholds
    h2("Best Config — Thresholds")
    best_t = r.best_strat_dict.get("thresholds", {})
    p("| Signal | Threshold |")
    p("|--------|-----------|")
    for k, v in best_t.items():
        p(f"| {k} | {v:+.1f} |")

    # Walk-forward folds
    h2("Walk-Forward Folds")
    p("| Fold | Train | Test | Train Sharpe | Test Sharpe | Test DD | Test CAGR |")
    p("|------|-------|------|-------------|------------|---------|----------|")
    for fold in r.wf_folds:
        tm = fold.test_metrics
        p(
            f"| {fold.fold} | {fold.train_start}→{fold.train_end} "
            f"| {fold.test_start}→{fold.test_end} "
            f"| {_f(fold.train_sharpe)} "
            f"| {_f(tm.get('sharpe_ratio'))} "
            f"| {_pct(tm.get('max_drawdown'))} "
            f"| {_pct(tm.get('cagr'))} |"
        )

    p()
    wf_beats = wf_m.get("cagr", 0.0) > h_bm.get("cagr", 0.0)
    p(f"**Walk-forward OOS**: Sharpe={_f(wf_m.get('sharpe_ratio'))}, "
      f"CAGR={_pct(wf_m.get('cagr'))}, MaxDD={_pct(wf_m.get('max_drawdown'))}")
    p(f"**Beats QQQ on OOS**: {'✅ Yes' if wf_beats else '❌ No'}")

    # Anti-overfitting
    h2("Anti-Overfitting Analysis")

    h3("1. Luck Audit")
    la = r.luck_audit
    p(f"- Completed trials: {la.get('n_completed_trials', 0)}")
    p(f"- Top 200 trials evaluated on holdout: {la.get('top_200_evaluated_on_holdout', 0)} configs")
    p(f"- Holdout 'winners' (beat QQQ): {la.get('n_holdout_winners', 0)} "
      f"({la.get('holdout_win_rate', 0)*100:.1f}%)")
    p(f"- Random null configs evaluated: {la.get('null_trials', 0)}")
    p(f"- Random null 'winners': {la.get('null_holdout_wins', 0)} "
      f"({la.get('null_win_rate', 0)*100:.1f}%)")
    p()
    p(f"**{la.get('assessment', '')}**")

    h3("2. Perturbation / Stability Test")
    pert = r.perturbation_results
    valid_pert = [p2 for p2 in pert if "error" not in p2]
    if valid_pert:
        sharpes = [p2["sharpe"] for p2 in valid_pert]
        cagrs   = [p2["cagr"]   for p2 in valid_pert]
        mean_s  = sum(sharpes) / len(sharpes)
        std_s   = math.sqrt(sum((x - mean_s)**2 for x in sharpes) / len(sharpes))
        mean_c  = sum(cagrs) / len(cagrs)

        best_holdout_sharpe = h_m.get("sharpe_ratio", 0.0)
        is_fragile = std_s > 0.3 * abs(best_holdout_sharpe) if best_holdout_sharpe != 0 else True

        p(f"Best config holdout Sharpe: **{_f(best_holdout_sharpe)}**")
        p(f"After {len(valid_pert)} ±5–10 pt weight nudges:")
        p(f"- Mean holdout Sharpe: {_f(mean_s)} (σ={_f(std_s)})")
        p(f"- Mean holdout CAGR: {_pct(mean_c)}")
        p()
        p(f"**{'⚠ FRAGILE' if is_fragile else '✅ STABLE'}**: "
          f"{'Performance collapses under small weight perturbations.' if is_fragile else 'Performance degrades gracefully under perturbation.'}")
    else:
        p("*(No valid perturbation results)*")

    h3("3. Top-Cluster Check")
    cl = r.cluster_analysis
    p(f"Top {cl.get('n_top_configs', 0)} configs by in-sample Sharpe:")
    p(f"- Average pairwise weight distance: {cl.get('avg_pairwise_distance', 0):.1f} pts")
    p()
    p(f"**{cl.get('assessment', '')}**")
    p()
    if cl.get("component_means"):
        p("| Component | Mean weight (top-N) | Std |")
        p("|-----------|-------------------|-----|")
        for name, mean in cl["component_means"].items():
            std = cl["component_stds"].get(name, 0.0)
            p(f"| {name} | {mean:.1f}% | ±{std:.1f}% |")

    # Honest assessment
    h2("Honest Assessment")
    p("The 10%-CAGR-over-QQQ goal is **very aggressive**. Any config achieving it "
      "must be treated as **SUSPECTED OVERFIT** until confirmed by:")
    p("- Passing the walk-forward check above")
    p("- Passing the perturbation stability test")
    p("- Positive live paper-trading results over ≥6 months")
    p()
    p("> **SURVIVORSHIP BIAS**: The universe uses CURRENT index membership. "
      "Companies delisted or removed during the backtest period are absent — "
      "this inflates all performance metrics. Treat results as an upper bound.")

    # Candidate file location
    h2("Candidate Config")
    if candidate_path:
        p(f"Best config saved to: `{candidate_path}`")
        p()
        p("**Do NOT use this automatically.** To promote to live:")
        p("```bash")
        p(f"cp {candidate_path.name} config.yaml")
        p("```")
        p("Then restart the backend: `scripts/launch.sh --no-build`")

    content = "\n".join(lines)
    out.write_text(content)
    return out

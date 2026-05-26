# MOD-I — Strategy optimizer with overfitting protection (train / holdout / walk-forward)

> Depends on mod-e + mod-f (backtest engine, fees, benchmark, metrics). Run AFTER them.
> In Claude Code:  `Read prompts/mod-i.md and execute it. Stop and report back when done.`
>
> EDIT POINTS: search the file for {{EDIT}} — there are a few knobs you may want to change.

```text
Read CLAUDE.md, config.yaml, API_CONTRACT.md, and the existing backtest code
(backend/app/backtest/ incl. mod-e per-profile + mod-f money management/benchmark/metrics).
Run `git commit -m "checkpoint before mod-i"` and `pytest -q` first. STOP if baseline fails.

CONTEXT / GOAL
I want to TUNE the long (and later short) strategy so it beats the benchmark (QQQ/SPY) on a
risk-adjusted basis over ~5 years on my universe. Doing this by hand is slow. Build an
OPTIMIZER that automates the search — BUT the #1 design requirement is to AVOID OVERFITTING.
Hitting a return target by searching historical data is meaningless unless it survives data
the optimizer never saw. Treat overfitting protection as the primary feature, not an add-on.

NON-NEGOTIABLE METHODOLOGY (build exactly this)
1. DATA SPLIT. Given a date range (default last {{EDIT: 5}} years), split chronologically:
   - IN-SAMPLE (training): the FIRST ~70% of the period.   {{EDIT: 0.70}}
   - HOLDOUT (out-of-sample): the LAST ~30%. The optimizer must NEVER read holdout results
     during the search. Enforce this in code (the search objective only sees in-sample).
2. OPTIMIZE ON IN-SAMPLE ONLY. Search parameter combinations, backtest each on the
   in-sample window using the EXISTING mod-f portfolio engine (fees, sizing, benchmark, all
   real), and score each by the OBJECTIVE below.
3. VALIDATE ON HOLDOUT. Take the single best in-sample config, run it ONCE on the holdout
   (untouched data), and report how it did there. A big drop from in-sample to holdout =
   overfit; say so plainly.
4. WALK-FORWARD (second pass, gold standard). Roll the train/test split across the history
   in {{EDIT: 4}} folds: optimize on each train slice, test on the following unseen slice,
   stitch the out-of-sample results into one equity curve. Report aggregate walk-forward
   metrics. A strategy that only works in one split but not walk-forward is not robust.

SEARCH METHOD — AGGRESSIVE (James chose wide search, accepts overfit risk)  {{EDIT}}
- Use Optuna (TPE/Bayesian sampler). Justify briefly why this over grid search.
- AGGRESSIVE search budget: max_trials = {{EDIT: 2000}} per optimization. Set a random seed
  for reproducibility. Log every trial (params + in-sample objective + whether it beat the
  benchmark on in-sample) to SQLite so I can review.
- BECAUSE the search is aggressive, you MUST run the "multiple-comparisons defenses" below —
  with this many trials, some configs will clear the success gates by pure luck, so a single
  holdout pass is NOT sufficient proof on its own.

PARAMETERS TO SEARCH (aggressive: free more knobs)  {{EDIT}}
- Phase 1 (ON): the 8 component WEIGHTS (constrained to sum to 100) and the signal THRESHOLDS.
- Phase 2 (ON by default given aggressive choice): the per-pattern scoring tables.
- Phase 3 (optional flag): position_size_pct and max_concurrent.
- Note in the report: freeing the scoring tables materially increases overfitting risk —
  this is the tradeoff I accepted by choosing aggressive. Make it easy to turn Phase 2 OFF
  via a flag if I later want a more conservative, robust search.

OBJECTIVE FUNCTION (what "better" means)  {{EDIT}}
Default objective = maximize in-sample SHARPE RATIO, NOT raw return. Rationale: optimizing
raw return picks the luckiest high-variance config; Sharpe rewards consistency and resists
overfitting better. Apply a penalty/constraint so the search prefers robust configs:
   - HARD CONSTRAINT: max_drawdown must stay below {{EDIT: 25%}} on in-sample; reject configs
     that breach it.
   - Report, but don't optimize directly for, CAGR vs benchmark (so I can see the 10%-CAGR
     goal without the search gaming it).
SUCCESS CRITERIA for a config to be "worth paper-trading" (report a clear PASS/FAIL).
James chose: beat on holdout AND a drawdown limit I set. So:
   - Beats the benchmark (QQQ default; also report vs SPY) on the HOLDOUT period, AND
   - Holdout max drawdown ≤ MAX_DRAWDOWN_LIMIT = {{EDIT: 25%}}  ← set my own number here, AND
   - WALK-FORWARD out-of-sample aggregate ALSO beats the benchmark AND respects the same
     drawdown limit.
   Because the search is AGGRESSIVE, treat WALK-FORWARD as the real verdict — a single
   holdout pass can happen by luck across 2000 trials. State honestly that the
   10%-CAGR-over-benchmark goal is very aggressive and that any config hitting it must be
   treated as SUSPECTED OVERFIT until walk-forward + the perturbation test (below) confirm it.

ANTI-OVERFITTING REPORTING (make the danger visible)
For the best config, show side by side: in-sample vs holdout vs walk-forward metrics
(CAGR, Sharpe, max DD, return vs benchmark). A large in-sample→holdout degradation must be
called out explicitly as likely overfitting. Also report how many of the {{max_trials}}
configs beat the benchmark in-sample — if "lots," warn that beating it is easy by chance
and holdout is what matters.

MULTIPLE-COMPARISONS DEFENSES (REQUIRED because the search is aggressive — 2000 trials)
These exist because with thousands of trials, some configs WILL pass the gates by luck.
Build all three and put them in the report:
1. LUCK AUDIT. Report: of N trials, how many beat the benchmark on the HOLDOUT, and roughly
   how many you'd expect to by chance alone. If observed ≈ expected-by-chance, state plainly
   that the "winner" is probably noise. (A simple way to estimate the chance baseline: run a
   modest number of RANDOM/shuffled-signal configs through the same holdout test and see how
   often they "win." Include this null-comparison count.)
2. PERTURBATION / STABILITY TEST. Take the best config and re-run the holdout with small
   random nudges to its weights (e.g. ±5–10 points redistributed, a dozen variations). A
   REAL edge degrades gracefully; an OVERFIT one collapses. Report the spread of holdout
   results under perturbation and flag the config as FRAGILE if performance falls apart.
3. TOP-CLUSTER CHECK. Look at the top ~20 in-sample configs: are their parameters CLUSTERED
   (similar weights → a real region of edge) or SCATTERED (random winners → overfit)? Report
   which, because clustered winners are far more trustworthy than scattered ones.
Final verdict must weigh walk-forward + these three defenses, NOT just the single holdout.

OUTPUT / API / CLI
- CLI: scripts/optimize.py --strategy long --start ... --end ... [--include-scoring-tables]
  [--include-sizing] that runs the full pipeline and writes a report.
- Persist: every trial, the best config, and the in-sample/holdout/walk-forward comparison
  to SQLite. Save the best config as a SEPARATE candidate file (e.g.
  config.candidate.long.yaml) — do NOT auto-overwrite my live config.yaml. I promote it
  manually only if I'm satisfied.
- Optional API endpoint POST /api/optimize (background job) + GET /api/optimize/{id};
  if added, update API_CONTRACT.md. CLI is the priority.
- Produce a human-readable markdown report at reports/optimize_<strategy>_<date>.md with
  the comparison tables and the PASS/FAIL verdict — this is what I'll hand to Cowork to
  interpret.

PERFORMANCE
- The search runs hundreds of backtests; make a single in-sample backtest fast enough that
  {{max_trials}} trials finish in a reasonable time (parallelise across symbols/CPU cores
  if needed). Report the wall-clock time for one full optimization.

TESTS
- Prove the holdout is never used by the objective (e.g. a test that the objective function
  has no access to holdout dates).
- Prove weight constraints hold (sum to 100) for every sampled config.
- Determinism: same seed + same data ⇒ same best config.
- A tiny toy run (few symbols, few trials) completes end to end in a unit/integration test.

ACCEPTANCE
- One command optimizes the long strategy on in-sample, validates on holdout, runs
  walk-forward, and writes a markdown report with a clear PASS/FAIL and the three-way
  metric comparison.
- My live config.yaml is untouched; the winner is saved as a candidate file I promote myself.

MANUAL STEPS FOR JAMES
Show me: (1) the exact command to optimize the long strategy over 5 years on my combined
universe; (2) how to read the report and where the candidate config is saved; (3) exactly
how to promote a candidate config to live (the file copy / command) once I'm satisfied;
(4) how to do the same for the short strategy.

REPORT BACK
Run a real optimization on the long strategy and show me the in-sample vs holdout vs
walk-forward comparison and the PASS/FAIL verdict. Tell me honestly whether the result looks
robust or overfit, and whether it realistically approaches the (very aggressive) 10%-CAGR-
over-QQQ goal. Then `git commit`. Do NOT promote any config to live.
```

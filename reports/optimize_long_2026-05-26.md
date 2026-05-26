# Optimisation Report — Long Strategy — 2026-05-26

*Generated 2026-05-26 · AlphaSignalV2 MOD-I*

## Summary

- **Universe**: 25 symbols
- **Full period**: 2021-05-27 → 2026-05-22
- **In-sample** (70%): 2021-05-27 → 2024-11-20
- **Holdout** (30%): 2024-11-21 → 2026-05-22
- **Trials completed**: 2000
- **Wall clock**: 32.0 min
- **Best in-sample Sharpe**: 1.93


## Verdict: ❌ FAIL

- FAIL: Holdout CAGR (15.0%) does not beat QQQ (27.0%)
- FAIL: Walk-forward OOS CAGR (12.1%) does not beat QQQ

## In-Sample vs Holdout vs Walk-Forward

| Metric | In-Sample | Holdout | Walk-Forward OOS |
|--------|-----------|---------|-----------------|
| CAGR | +25.6% | +15.0% | +12.1% |
| Sharpe ratio | 1.93 | 1.29 | 1.37 |
| Max drawdown | +10.9% | +9.6% | +7.8% |
| Total return | +121.3% | +23.2% | +57.8% |
| Win rate | 0.43 | 0.41 | 0.40 |
| Profit factor | 2.03 | 1.51 | 1.67 |


## Benchmark Comparison (Holdout)

| Metric | Strategy | QQQ | SPY | Beats QQQ? |
|--------|----------|-----|-----|-----------|
| CAGR | +15.0% | +27.0% | +17.9% | ❌ |
| Sharpe | 1.29 | 1.21 | 1.02 | ✅ |
| Max drawdown | +9.6% | +22.8% | +18.8% | ❌ |
| Total return | +23.2% | +42.7% | +27.8% | ❌ |

## Best Config — Weights

| Component | Weight |
|-----------|--------|
| macd | 22.9% |
| ema | 20.9% |
| p5 | 12.9% |
| p3 | 12.5% |
| volume | 11.4% |
| candlestick | 9.1% |
| sr | 7.0% |
| rsi | 3.2% |

## Best Config — Thresholds

| Signal | Threshold |
|--------|-----------|
| strong_buy | +50.2 |
| buy | +41.5 |
| sell | -41.5 |
| strong_sell | -50.2 |

## Walk-Forward Folds

| Fold | Train | Test | Train Sharpe | Test Sharpe | Test DD | Test CAGR |
|------|-------|------|-------------|------------|---------|----------|
| 1 | 2021-05-27→2022-05-23 | 2022-05-24→2023-05-22 | 2.36 | -0.01 | +7.8% | -0.4% |
| 2 | 2021-05-27→2023-05-22 | 2023-05-23→2024-05-20 | 1.73 | 2.87 | +7.0% | +33.1% |
| 3 | 2021-05-27→2024-05-20 | 2024-05-21→2025-05-20 | 2.39 | 1.21 | +6.1% | +12.1% |
| 4 | 2021-05-27→2025-05-20 | 2025-05-21→2026-05-22 | 1.96 | 1.01 | +6.4% | +6.5% |

**Walk-forward OOS**: Sharpe=1.37, CAGR=+12.1%, MaxDD=+7.8%
**Beats QQQ on OOS**: ❌ No

## Anti-Overfitting Analysis


### 1. Luck Audit

- Completed trials: 2000
- Top 200 trials evaluated on holdout: 200 configs
- Holdout 'winners' (beat QQQ): 0 (0.0%)
- Random null configs evaluated: 50
- Random null 'winners': 0 (0.0%)

**⚠ Winner is likely NOISE: observed win rate is close to random baseline.**

### 2. Perturbation / Stability Test

Best config holdout Sharpe: **1.29**
After 12 ±5–10 pt weight nudges:
- Mean holdout Sharpe: 1.27 (σ=0.23)
- Mean holdout CAGR: +14.8%

**✅ STABLE**: Performance degrades gracefully under perturbation.

### 3. Top-Cluster Check

Top 20 configs by in-sample Sharpe:
- Average pairwise weight distance: 3.5 pts

**CLUSTERED (avg weight distance 3.5 points < 25) — top configs agree on similar weights, suggesting a real region of edge.**

| Component | Mean weight (top-N) | Std |
|-----------|-------------------|-----|
| candlestick | 8.7% | ±0.6% |
| p3 | 13.2% | ±1.4% |
| p5 | 13.8% | ±0.8% |
| volume | 11.8% | ±0.5% |
| ema | 20.6% | ±0.7% |
| sr | 6.4% | ±0.5% |
| macd | 22.7% | ±1.2% |
| rsi | 2.8% | ±1.7% |

## Honest Assessment

The 10%-CAGR-over-QQQ goal is **very aggressive**. Any config achieving it must be treated as **SUSPECTED OVERFIT** until confirmed by:
- Passing the walk-forward check above
- Passing the perturbation stability test
- Positive live paper-trading results over ≥6 months

> **SURVIVORSHIP BIAS**: The universe uses CURRENT index membership. Companies delisted or removed during the backtest period are absent — this inflates all performance metrics. Treat results as an upper bound.

## Candidate Config

Best config saved to: `/Users/jameswang/Documents/Claude/Code/AlphaSignalV2/config.candidate.long.yaml`

**Do NOT use this automatically.** To promote to live:
```bash
cp config.candidate.long.yaml config.yaml
```
Then restart the backend: `scripts/launch.sh --no-build`
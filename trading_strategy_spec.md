# Reversal & Trend-Following Trading Strategy — Implementation Spec

**Version:** 0.1 (draft)
**Author:** James Wang
**Purpose:** Implementation specification for a daily-timeframe reversal-detection and momentum-following trading strategy. This document is the source of truth for Claude Code to build the strategy engine.

---

## 1. Core Principle

> **Identify reversal signals; trade in the direction of confirmed momentum. Never trade against momentum.**

Two practical implications for the engine:

1. A reversal signal alone is not a trade signal. It must be confirmed by momentum/structure.
2. A "regime filter" gates every long and short signal before any score is computed (see §3).

---

## 2. Scoring System — Overview

* The strategy produces a single **composite score** per symbol per bar (default timeframe: daily).
* **Score range:** −100 to +100.
* Composite score = weighted sum of component sub-scores, where each component is normalized to its own −100 to +100 sub-scale and then multiplied by its weight (weight/100).
* Weights across all components sum to **100**.

### 2.1 Signal Thresholds

| Composite Score | Signal |
|---|---|
| > +85 | Strong Buy |
| +70 to +85 | Buy |
| −70 to +70 | Hold / No Action |
| −85 to −70 | Sell |
| < −85 | Strong Sell |

### 2.2 Default Component Weights

| # | Component | Weight | Notes |
|---|---|---:|---|
| 1 | Candlestick pattern | 12 | Current-bar pattern |
| 2 | P3 Pivot | 8 | 3-bar structure |
| 3 | P5 Pivot | 12 | 5-bar structure (more reliable than P3) |
| 4 | Volume (contextual) | 10 | Conditional on price direction — see §4.4 |
| 5 | EMA system | 15 | 20/50/100/200 EMAs |
| 6 | Support / Resistance | 15 | Bounce vs break |
| 7 | MACD | 18 | Includes divergence |
| 8 | RSI | 10 | Excludes divergence (handled in MACD) |
| **Total** | | **100** | |

**Note:** Divergence was removed from RSI to avoid double-counting with MACD. If you want divergence in both, reduce each component's divergence sub-weight by half.

---

## 3. Regime Filter (Pre-Score Gate)

Before computing the composite score, evaluate the regime filter. **If a side fails the filter, that side's score is clamped to 0.** (e.g., if long is gated out, any long signals do not contribute; only short side can fire.)

| Condition | Long allowed? | Short allowed? |
|---|---|---|
| Price > EMA200 AND EMA200 slope ≥ 0 | ✅ | ❌ (or with reduced weight) |
| Price < EMA200 AND EMA200 slope ≤ 0 | ❌ (or with reduced weight) | ✅ |
| Mixed / EMA200 flat | ✅ | ✅ (both allowed; range-bound regime) |

**EMA200 slope definition:** sign of (EMA200[today] − EMA200[20 bars ago]).

This is the explicit "never trade against momentum" gate.

---

## 4. Component Sub-Scoring

Each component outputs a sub-score in [−100, +100]. The component's contribution to the composite is `sub_score × (weight / 100)`.

### 4.1 Candlestick Pattern (weight 12)

| Pattern | Definition | Sub-score |
|---|---|---:|
| Long Bullish Candle | Body ≥ 70% of total range; close > open; large range | +90 |
| Green Hammer | Green body in upper 1/3; lower wick ≥ 2× body; minimal upper wick | +80 |
| Inverted Green Hammer | Green body in lower 1/3; upper wick ≥ 2× body; minimal lower wick | +55 |
| Bullish Spinning Top | Small green body centered; wicks on both sides | +25 |
| Bullish Doji | Open ≈ close (within 5% of range); appears at recent low | +20 |
| Bearish Doji | Open ≈ close; appears at recent high | −20 |
| Bearish Spinning Top | Small red body centered; wicks on both sides | −25 |
| Inverted Red Hammer (Shooting Star) | Red body in lower 1/3; upper wick ≥ 2× body | −80 |
| Red Hammer (Hanging Man) | Red body in upper 1/3; lower wick ≥ 2× body | −55 |
| Long Bearish Candle | Body ≥ 70% of total range; close < open; large range | −90 |
| No clear pattern | — | 0 |

**Context multiplier (optional, recommended):** Multiply pattern sub-score by 1.2 (capped at ±100) when the pattern occurs at a P5 pivot support/resistance level. This captures the "hammer at support is stronger than a hammer in mid-trend" effect.

### 4.2 P3 Pivot (weight 8)

P3 = window of the previous 3 candles, including current.

Detect pivot patterns:
* **Bullish reversal at support:** P3 forms a clear low; current bar closes higher than prior two; lower wicks on bars 1–2 indicate buying.
* **Bullish breakout:** Current bar closes above the high of the prior 2 bars and above a known resistance.
* **Continuation up:** All 3 bars closing progressively higher.
* **Mirror conditions** for bearish.

| P3 Pattern | Sub-score |
|---|---:|
| Bullish reversal at support | +70 |
| Bullish breakout above resistance | +60 |
| Continuation up | +30 |
| No clear pattern | 0 |
| Continuation down | −30 |
| Bearish breakdown below support | −60 |
| Bearish reversal at resistance | −70 |

### 4.3 P5 Pivot (weight 12)

Same logic as P3 but with a 5-bar window. P5 is more reliable; weights and scores are larger.

| P5 Pattern | Sub-score |
|---|---:|
| Major bullish reversal (clear 5-bar low + close higher) | +85 |
| Bullish trend confirmation (uptrend with HH+HL) | +50 |
| Range-bound | 0 |
| Bearish trend confirmation (downtrend with LH+LL) | −50 |
| Major bearish reversal | −85 |

### 4.4 Volume — Contextual (weight 10)

**Critical design point:** Volume itself is not directional. Volume is scored as an *amplifier* on top of the price direction of the current candle.

Relative volume (RV) = current bar volume ÷ 30-day average volume.

**If current candle is bullish (close > open):**

| RV bucket | Sub-score |
|---|---:|
| > 5.0× | +100 |
| 3.0× – 5.0× | +80 |
| 2.0× – 3.0× | +60 |
| 1.5× – 2.0× | +40 |
| 1.0× – 1.5× | +20 |
| 0.8× – 1.0× | 0 |
| 0.5× – 0.8× | −15 |
| 0.3× – 0.5× | −30 |
| 0.2× – 0.3× | −40 |
| < 0.2× | −50 |

**If current candle is bearish (close < open):** Invert all signs (RV > 5× on a red candle → −100).

**If candle is a doji or spinning top (no clear direction):** Sub-score = 0 regardless of volume.

### 4.5 EMA System (weight 15)

EMAs in use: **20, 50, 100, 200**.

Two contributing signals — take the **larger absolute value** as the final sub-score (preserving sign):

#### A. EMA Stacking (position-based)

| Condition | Sub-score |
|---|---:|
| Price > EMA20 > EMA50 > EMA100 > EMA200 (full bull stack) | +60 |
| Price above 3 of 4 EMAs | +30 |
| Price above 2 of 4 EMAs | 0 |
| Price below 3 of 4 EMAs | −30 |
| Price < EMA20 < EMA50 < EMA100 < EMA200 (full bear stack) | −60 |

#### B. EMA Cross Event (fires only on the cross bar)

| Event | Sub-score |
|---|---:|
| Price crosses above EMA200 | +95 |
| Price crosses above EMA100 | +75 |
| Price crosses above EMA50 | +55 |
| Price crosses above EMA20 | +35 |
| Price crosses below EMA20 | −35 |
| Price crosses below EMA50 | −55 |
| Price crosses below EMA100 | −75 |
| Price crosses below EMA200 | −95 |

**Final EMA sub-score:** Take max(|stack|, |cross|) with original sign.

### 4.6 Support / Resistance (weight 15)

Identification method (implementation choice; default below):
* Identify **swing highs** and **swing lows** using the P5 pivot window.
* Cluster adjacent swing levels within 1% of each other.
* The most recent unbroken cluster below current price = support; above = resistance.

| Event | Sub-score |
|---|---:|
| Strong bounce off support (close ≥ midpoint of range, range > avg) | +80 |
| Breakout above resistance (close above resistance with volume > 1.5×) | +85 |
| Approach support (touched, no bounce yet) | +20 |
| No interaction with key levels | 0 |
| Approach resistance (touched, no rejection yet) | −20 |
| Strong rejection off resistance | −80 |
| Breakdown below support (close below support with volume > 1.5×) | −85 |

### 4.7 MACD (weight 18)

Standard MACD: 12/26/9 (configurable).

Sub-score is the sum of micro-signals below, clipped to [−100, +100].

| Micro-signal | Contribution |
|---|---:|
| Golden cross (MACD line crosses signal line up) on current bar | +35 |
| Death cross on current bar | −35 |
| MACD line above zero | +15 |
| MACD line below zero | −15 |
| Histogram: green and expanding (current bar > prior bar) | +20 |
| Histogram: green and contracting | +5 |
| Histogram: red and expanding (more negative than prior) | −20 |
| Histogram: red and contracting | −5 |
| Bullish divergence (price makes lower low, MACD makes higher low) | +30 |
| Bearish divergence (price makes higher high, MACD makes lower high) | −30 |

**Final MACD sub-score = clip(sum of triggered micro-signals, −100, +100).**

### 4.8 RSI (weight 10)

Default: RSI(14).

| Condition | Sub-score |
|---|---:|
| RSI crosses up through 30 (exit oversold) | +70 |
| RSI < 30 and rising | +40 |
| RSI < 30 and falling | −10 |
| RSI 30–50 and rising | +25 |
| RSI 30–50 and falling | −15 |
| RSI 50–70 and rising | +25 |
| RSI 50–70 and falling | −15 |
| RSI > 70 and rising | +10 |
| RSI > 70 and falling | −40 |
| RSI crosses down through 70 (exit overbought) | −70 |

Divergence handled in MACD — do not score here.

---

## 5. Final Score Computation

```
1. Compute regime filter. Determine long_allowed, short_allowed.
2. For each component i in [candlestick, p3, p5, volume, ema, sr, macd, rsi]:
   - sub_score_i = function defined in §4
   - weighted_i  = sub_score_i × (weight_i / 100)
3. raw_composite = sum of all weighted_i
4. Apply regime gate:
   - if raw_composite > 0 and not long_allowed: composite = 0
   - if raw_composite < 0 and not short_allowed: composite = 0
   - else: composite = raw_composite
5. Map composite to signal per §2.1.
```

---

## 6. Implementation Notes for Claude Code

### 6.1 Data Layer

* Use a Python library for OHLCV ingest (e.g., `yfinance`, `pandas-datareader`, or a paid feed). Default to **daily bars**.
* Universe is configurable; start with a watchlist file (CSV: symbol, exchange).
* Cache historical data locally (Parquet or SQLite) to avoid re-fetching.

### 6.2 Compute Layer

* Use `pandas` + `pandas-ta` (or `ta-lib` if available) for EMAs, MACD, RSI.
* Implement pivot, candlestick, and S/R detection as standalone functions in `indicators/` module.
* Implement each component scoring function in `scoring/<component>.py`.
* Composite engine in `scoring/composite.py`.

### 6.3 Output Layer

* Daily signal table per symbol: date, composite score, signal, contributing sub-scores, regime status.
* Persist to SQLite or Parquet. Expose via CLI initially; web UI later.

### 6.4 Configuration

* All weights, thresholds, and scoring tables live in a single `config.yaml` so they can be tuned without code changes.

### 6.5 Backtest Harness (not in scope for v1 but design for it)

* Vectorized backtester: walk bar-by-bar through history, generate signals, simulate fills with configurable slippage.
* Metrics: hit rate, average win/loss, max drawdown, Sharpe, exposure.

---

## 7. Open Questions / Decisions Needed

| # | Question | Default if not answered |
|---|---|---|
| 1 | Asset universe? (US stocks? ASX? crypto?) | US large/mid-cap, top 500 by liquidity |
| 2 | Timeframe — daily only, or multi-timeframe confirmation? | Daily only for v1 |
| 3 | Risk management: stop-loss method? (% based, ATR-based, structure-based) | 1.5 × ATR(14) below entry for longs |
| 4 | Position sizing: fixed %, volatility-based, Kelly? | 2% account risk per trade |
| 5 | Profit target / exit rule? | Trail stop at 1.5 × ATR, exit on opposite signal |
| 6 | Max concurrent positions? | 10 |
| 7 | Re-entry rules after stop-out? | Cooldown of 5 bars |
| 8 | Earnings / news blackout? | Skip signals within 3 bars of earnings |
| 9 | How to identify support/resistance levels algorithmically? | P5-swing + 1% clustering (see §4.6) |
| 10 | Should weights/scores adapt to volatility regime? | Static for v1; revisit after backtest |

---

## 8. Acceptance Criteria for v1

1. Given a watchlist and a date range, produce a daily signal table with composite scores.
2. Sub-scores per component must be auditable (each must be visible in the output).
3. Regime filter must be observable per bar.
4. All weights and thresholds must be modifiable via `config.yaml`.
5. Code must include unit tests for each component's scoring function with at least 3 test cases each.
6. End-to-end run on a 100-symbol watchlist for 1 year of history must complete in under 5 minutes on M-series MacBook.

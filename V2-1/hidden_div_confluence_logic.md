# Hidden Divergence Confluence — Uptrend Swing

**Plain-English logic specification.** This is the source of truth for the indicator. If you ever want to rebuild the Pine script from scratch, or change behaviour, edit this file first, then make the code match it.

Companion file: `hidden_div_confluence_uptrend.pine` (TradingView Pine Script v6).

---

## 1. What it does, in one paragraph

It hunts for pullback **entries** inside an established **uptrend** and exhaustion-based **exits**. An entry is a *higher low* where momentum is washing out (hidden bullish divergence), confirmed by a weighted confluence score. Exits are deliberately easier to trigger than entries — you protect capital on less evidence than you require to commit it. The whole entry engine only runs while the market is in a confirmed uptrend (regime gate). Everything is calculated on confirmed bars, so signals are reliable but arrive a few bars after the actual turn.

Mental model: **enter at a higher low, exit at a higher high.**

---

## 2. The key concept: hidden vs regular divergence

Divergence = price and momentum disagree at consecutive pivots.

| Pattern | Price does | Momentum does | Meaning | Used for |
|---|---|---|---|---|
| **Hidden bullish** | Higher low | Lower low | Pullback selling is exhausting → uptrend resumes | **Entries** |
| **Regular bearish** | Higher high | Lower high | Rally is exhausting at the top | **Exits** |

This is the correction we made early on: a *regular* bullish divergence needs a *lower* low in price and never fires at the higher-low pullbacks we actually buy. **Hidden** bullish divergence is the continuation pattern that matches "enter at HL in an uptrend." Don't confuse the two — it changes the entire detection logic.

---

## 3. Regime gate (entries only)

The entry engine is switched **off** unless all of the following are true on the current bar:

- EMA50 is above EMA200 (bullish structure)
- EMA50 is rising (higher than it was `slopeLook` bars ago)
- EMA200 is rising
- Close is **above EMA200**

Deliberate design choice: we do **not** require price above EMA50. Healthy pullbacks routinely tag or briefly pierce the 50 — that is exactly where the best higher lows form. Gating on EMA50 would filter out the entries we want. So the gate confirms the *structure* and the *slow line*, and lets price dip toward/below the fast line.

Exits are **not** gated — they can fire any time, because you might be holding a position when the regime starts to break.

---

## 4. Entry logic

A **BUY** fires when **all three** hold:

1. The regime gate is true, **and**
2. A divergence (MACD or RSI hidden bullish) confirmed on this bar, **and**
3. The entry score is at or above the threshold.

### Entry score (0–100)

| Component | Weight | What it is |
|---|---|---|
| MACD hidden bullish divergence | 35 | Core thesis (momentum via MACD) |
| RSI hidden bullish divergence | 35 | Core thesis, different lens |
| RSI in the 40–55 pullback zone | 20 | Location filter — confirms a healthy pullback |
| DeMark TD9 buy setup | 10 | Downside-exhaustion booster (kept small on purpose) |

**Default entry threshold = 65.**

What 65 buys you:

- Both divergences = 70 → fires.
- One divergence + zone + DeMark = 65 → fires.
- One divergence + only one supporting piece (≤ 55) → does **not** fire.
- No divergence at all → can never reach 65. By design — an entry always requires at least one genuine divergence, and no single indicator can trigger it alone.

**Tuning dial:** this threshold is your selectivity knob. Raise to **70** to force *both* divergences (fewer, higher-conviction signals). Lower toward **55** for more frequency.

### Why a 40–55 RSI zone (not 30)

In an established uptrend RSI oscillates in a higher band (~40–80) and rarely touches 30. A dip into 40–55 during a pullback is a *buy zone*, not an oversold warning. That is the absolute level we reward.

---

## 5. Exit logic

A **SELL** fires when **both** hold:

1. An exit event confirmed on this bar (any bearish divergence or DeMark sell event), **and**
2. The exit score is at or above the (low) exit threshold.

### Exit score (0–100)

| Component | Weight | What it is |
|---|---|---|
| DeMark TD13 sell countdown | 40 | Strong upside exhaustion |
| MACD regular bearish divergence | 35 | Topping momentum |
| RSI regular bearish divergence | 35 | Topping momentum |
| DeMark TD9 sell setup | 20 | Upside exhaustion |

**Default exit threshold = 35.** Any single bearish divergence (35), or a TD13 (40), fires the exit on its own. A lone TD9 sell (20) needs a partner.

**Tuning dial:** lower toward **20** for a twitchier exit. This is the asymmetry you asked for — exits act on less evidence than entries.

---

## 6. Confluence window (why scoring beats a strict "AND")

The components almost never peak on the *same* bar — MACD and RSI pivots differ, DeMark completes on its own schedule. A strict "all three on one bar" rule would produce a near-empty chart and nothing to optimise.

So each component counts toward the score if it occurred within `confWin` bars (default 10 for entries, 5 for exits) of the trigger bar. The score is a number you can move, which is what makes it tunable in AlphaSignal.

A **cooldown** equal to the window prevents the same pullback from firing multiple buy signals.

---

## 7. The indicators, briefly

- **EMA50 / EMA200** — exponential moving averages defining trend structure and slope.
- **MACD** (12/26/9) — divergence is measured on the **MACD line**. (To use the histogram instead, change one line in the script — noted in the code.)
- **RSI** (14) — used both for divergence and for the 40–55 zone filter.
- **Pivots** — a swing low/high confirmed only after `lbR` bars of higher/lower bars on its right. This is what makes the script non-repainting (see §10).
- **DeMark TD Sequential** — a trend-exhaustion timer, *not* a divergence:
  - **TD9 setup** = 9 consecutive closes each lower (buy setup) or higher (sell setup) than the close `tdFlipLook` bars earlier.
  - **TD13 countdown** = 13 qualifying closes after a completed setup. Sell countdown qualifier: close ≥ high two bars earlier.
  - **In this strategy:** TD9 *buy* setup boosts an entry (pullback selling exhausting). TD9 *sell* setup and TD13 *sell* countdown drive exits.

---

## 8. What you see on the chart

| Marker | Meaning |
|---|---|
| Green triangle (below bar) | Confluence **BUY** signal |
| Red triangle (above bar) | Confluence **SELL** signal |
| Green / red **circle** + "MACD" | Individual MACD divergence (hidden bull / regular bear) |
| Green / red **square** + "RSI" | Individual RSI divergence (Pine has no rectangle marker; square stands in) |
| **Yellow star** + "DeMark 9" | TD9 setup (below bar = buy/downside, above bar = sell/upside) |
| **Red star** + "DeMark 13" | TD13 countdown (below = buy, above = sell) |
| Green background shade | Regime gate is active (uptrend) |
| EMA50 (blue) / EMA200 (orange) | Trend structure |
| S/R boxes | Support/resistance zones, coloured by strength |

Each layer has its own on/off toggle. The triangles are the only *actionable* signals; the circles/squares/stars are there so you can see which components contributed (and debug).

### Support / Resistance by strength

S/R levels are built from price pivots. Pivots that cluster within a tolerance (default 0.5 × ATR14) are merged into one zone, and each touch raises that zone's **strength**. Strength is colour-coded:

- 1 touch → faint gray
- 2 touches → orange
- 3+ touches → red, and more opaque the stronger it is

This is the most cosmetic part and is intentionally not over-built.

---

## 9. Alerts

Two kinds:

- A rich **`alert()`** for the BUY and SELL confluence signals, with a dynamic message containing ticker, price and score.
- An **`alertcondition()`** for each individual signal, so you can switch them on/off as separate checkboxes in TradingView's alert dialog.

**Critical rule:** when you create any of these alerts, choose **"Once Per Bar Close."** "Once Per Bar" would fire intrabar on an unconfirmed pivot that can then vanish — i.e. false alerts.

---

## 10. Non-repainting and porting to AlphaSignal

### Non-repainting

All divergences use **confirmed** pivots. A pivot is only known `lbR` bars after it prints, so signals appear a few bars **after** the actual low/high. The trade-off: reliable-but-lagged vs at-the-low-but-repainting. We chose reliability. On daily swing bars a 1–5 bar lag is fine.

### What ports to Python (logic only)

Replicate these exactly or the backtest will not match live:

1. **Pivot confirmation lag.** A signal occurs at `low + lbR`, not at the low. Your Python pivot detection must use the same left/right bars and the same lag.
2. **DeMark rules.** The script uses a *simplified* TD Sequential (see §11). Port the same simplified rules — don't swap in a different library's "full" implementation, or the signals diverge.
3. **Price series.** Decide adjusted vs unadjusted close and use the **same** on both TradingView and yfinance. yfinance gives both `Close` and `Adj Close`; pick one and stick to it.

### What does NOT port (and doesn't need to)

Visualisations, support/resistance zones, and alerts are TradingView-only and have nothing to do with backtesting or optimisation. Ignore them entirely on the Python side.

---

## 11. Known simplifications and honest caveats

- **DeMark is simplified.** Setup and countdown are implemented in standard form, with a basic cancellation (an opposite setup cancels a countdown). Perfection, recycle, and some cancellation nuances are omitted. Cross-check this against your Python port — it is the single hardest piece to keep identical across both platforms.
- **RSI is partly double-counted.** RSI divergence (structure) and the RSI 40–55 zone (location) can both fire on the same setup. This is a deliberate lean toward "RSI strongly confirms," not a bug. If it skews backtests, cap RSI's combined contribution.
- **MACD divergence uses the MACD line**, not the histogram. Both are defensible; one line in the code switches it.
- **Individual markers are not regime-gated** — they show everywhere so you can see context. Only the confluence triangles respect the regime gate.

---

## 12. Parameter reference (defaults)

| Group | Parameter | Default |
|---|---|---|
| Regime | EMA fast / slow / slope lookback | 50 / 200 / 5 |
| Pivots | Left / right bars | 5 / 5 |
| Pivots | Min / max bars between pivots | 5 / 60 |
| MACD | Fast / slow / signal | 12 / 26 / 9 |
| RSI | Length | 14 |
| RSI | Buy zone low / high | 40 / 55 |
| DeMark | Setup / countdown | 9 / 13 |
| DeMark | Setup / countdown compare lookback | 4 / 2 |
| Entry weights | MACD / RSI / zone / TD9 | 35 / 35 / 20 / 10 |
| Entry | Threshold | 65 |
| Entry | Confluence window (+ buy cooldown) | 10 |
| Exit weights | MACD / RSI / TD13 / TD9 | 35 / 35 / 40 / 20 |
| Exit | Threshold | 35 |
| Exit | Confluence window (+ sell cooldown) | 5 |
| S/R | Pivot left / right | 10 / 10 |
| S/R | Merge tolerance (× ATR14) | 0.5 |
| S/R | Max zones / box length | 12 / 60 |

---

## 13. Change log

- v1.0 — initial build. Hidden bullish entries, regular bearish + DeMark exits, regime gate (structure + price > EMA200), weighted confluence scoring, S/R by strength, alerts (once-per-bar-close).

# PHASE 2 — Indicators + scoring engine (THE CORE)

> Paste-free workflow: in Claude Code just type — Read prompts/phase-2.md and execute it. Stop and report when done.

Read CLAUDE.md, trading_strategy_spec.md (§3–§5) and trading_strategy_template.xlsx.
We're building the INDICATORS and SCORING ENGINE. Read every weight/score from
config.yaml — never hard-code them.

GOAL
Given a symbol's daily OHLCV history, compute per-bar: each component sub-score, the
regime gate, and the final composite score + signal label — exactly as the spec defines.

BUILD — indicators (pure functions, backend/app/indicators/)
- ema.py (20/50/100/200 + slope), macd.py (12/26/9), rsi.py (14).
- pivots.py (P3 & P5 swing detection), candlestick.py (all patterns in spec §4.1),
  support_resistance.py (P5-swing + 1% clustering, spec §4.6).
- atr.py (ATR14 — needed later for risk).

BUILD — scoring (backend/app/scoring/, one module per component)
- candlestick.py, p3.py, p5.py, volume.py (CONTEXTUAL — sign depends on candle direction,
  spec §4.4), ema.py (max(|stack|,|cross|) preserving sign, §4.5), support_resistance.py,
  macd.py (sum micro-signals then clip ±100, §4.7, divergence scored HERE),
  rsi.py (§4.8, NO divergence here).
- regime.py: implement the EMA200 gate (§3). Output {long_allowed, short_allowed}.
- composite.py: implement spec §5 exactly:
   1) regime gate, 2) per-component weighted sub-scores, 3) raw_composite,
   4) clamp to 0 if the gated side isn't allowed, 5) map to signal via §2.1 thresholds.
- The composite output for each bar must be an auditable object:
   {date, composite, signal, regime:{long_allowed,short_allowed},
    components:{candlestick:{sub,weight,weighted}, ... per component}}.

TESTS (mandatory — spec acceptance criterion #5)
- For EACH scoring component, ≥3 unit tests with hand-constructed bars proving the right
  sub-score (e.g. a textbook green hammer at support → expected candlestick sub-score).
- A composite test reproducing the Example_Calc tab from the xlsx (it rolls up to 63.15
  → HOLD). This is your golden test: composite.py must reproduce it.
- A look-ahead test: prove that the signal for bar T is unchanged if future bars are
  deleted from the input.

ACCEPTANCE
- `pytest -q` passes, including the Example_Calc golden test (composite = 63.15, HOLD).
- Running the engine over cached AAPL history produces a per-bar auditable signal table.

REPORT BACK
Show the audit object for the latest AAPL bar with every sub-score visible. List any
spec ambiguities you resolved and how. Do NOT start Phase 3.

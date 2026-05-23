"""Composite scoring engine. Implements spec §5.

Two public surfaces:
  score_bar(sub_scores, weights, regime, thresholds) → dict
      Pure rollup — used by the Example_Calc golden test and the engine internals.

  run_engine(df, cfg, strategy) → list[dict]
      Full pipeline: indicators → per-component scores → regime gate → composite → signal.
      Each element is an auditable object for one bar.
      ``strategy`` selects which profile ("long" | "short") to use; defaults to "long".
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from backend.app.config import AppConfig, Thresholds, Weights
from backend.app.indicators.atr import compute_atr
from backend.app.indicators.candlestick import detect_candlestick_pattern
from backend.app.indicators.ema import compute_emas
from backend.app.indicators.macd import compute_macd
from backend.app.indicators.pivots import detect_p3_pattern, detect_p5_pattern
from backend.app.indicators.rsi import compute_rsi
from backend.app.indicators.support_resistance import compute_sr_levels
from backend.app.scoring.candlestick import score_candlestick
from backend.app.scoring.ema import score_ema
from backend.app.scoring.macd import score_macd
from backend.app.scoring.p3 import score_p3
from backend.app.scoring.p5 import score_p5
from backend.app.scoring.regime import compute_regime
from backend.app.scoring.rsi import score_rsi
from backend.app.scoring.support_resistance import score_sr
from backend.app.scoring.volume import score_volume


# ── Signal mapping ─────────────────────────────────────────────────────────────

def _map_signal(composite: float, t: Thresholds) -> str:
    """Map composite score to signal label (spec §2.1)."""
    if composite > t.strong_buy:
        return "Strong Buy"
    if composite >= t.buy:
        return "Buy"
    if composite <= t.strong_sell:
        return "Strong Sell"
    if composite <= t.sell:
        return "Sell"
    return "Hold"


# ── Pure rollup (used by golden test and engine) ───────────────────────────────

def score_bar(
    sub_scores: dict[str, float],
    weights: Weights,
    regime: dict[str, bool],
    thresholds: Thresholds,
) -> dict:
    """Apply weights, regime gate, and signal mapping to a dict of sub-scores.

    Returns the auditable bar object (without a date field — caller adds it).
    """
    components: dict[str, dict] = {}
    raw_composite = 0.0

    for name, sub in sub_scores.items():
        weight = float(getattr(weights, name))
        weighted = sub * (weight / 100.0)
        raw_composite += weighted
        components[name] = {
            "sub": round(sub, 6),
            "weight": weight,
            "weighted": round(weighted, 6),
        }

    # Regime gate (spec §5 step 4)
    if raw_composite > 0 and not regime["long_allowed"]:
        composite = 0.0
    elif raw_composite < 0 and not regime["short_allowed"]:
        composite = 0.0
    else:
        composite = raw_composite

    return {
        "composite": round(composite, 6),
        "signal": _map_signal(composite, thresholds),
        "regime": regime,
        "components": components,
    }


# ── Full engine ────────────────────────────────────────────────────────────────

def run_engine(
    df: pd.DataFrame,
    cfg: AppConfig,
    strategy: Literal["long", "short"] = "long",
) -> list[dict]:
    """Run the complete scoring pipeline over a daily OHLCV DataFrame.

    Args:
        df: DataFrame with columns [open, high, low, close, volume] and a DatetimeIndex.
        cfg: Loaded AppConfig.
        strategy: Which profile to use — "long" (default) or "short".

    Returns:
        List of auditable bar dicts (one per row), ordered oldest → newest.
        Each dict: {date, composite, signal, regime, components, strategy}.

    No look-ahead: all indicator and scoring functions are backward-looking only.
    """
    if df.empty:
        return []

    strat = cfg.get_strategy(strategy)

    # ── Indicators ────────────────────────────────────────────────────────────
    ema_df = compute_emas(df, strat.ema.periods, strat.regime.slope_lookback)
    macd_df = compute_macd(df, strat.macd.fast, strat.macd.slow, strat.macd.signal)
    rsi_s = compute_rsi(df, strat.rsi.period)
    atr_s = compute_atr(df, cfg.risk.stop_loss_atr_period)  # noqa: F841 (used in Phase 3)
    candle_s = detect_candlestick_pattern(
        df,
        long_candle_body_pct=strat.candlestick.long_candle_body_pct,
        hammer_wick_mult=strat.candlestick.hammer_wick_mult,
        doji_body_pct=strat.candlestick.doji_body_pct,
    )
    p3_s = detect_p3_pattern(df)
    p5_s = detect_p5_pattern(df)
    sr_df = compute_sr_levels(df, strat.sr.cluster_pct)

    # ── Regime ────────────────────────────────────────────────────────────────
    regime_df = compute_regime(df["close"], ema_df, strat.regime)

    # ── at_sr flag for candlestick context multiplier ─────────────────────────
    support = sr_df["support_level"]
    resistance = sr_df["resistance_level"]
    tol = 0.005  # 0.5% proximity to qualify as "at S/R"
    at_sr = (
        (support.notna() & ((df["low"] - support).abs() / support <= tol))
        | (resistance.notna() & ((df["high"] - resistance).abs() / resistance <= tol))
    )

    # ── Scoring ───────────────────────────────────────────────────────────────
    cs_scores = score_candlestick(candle_s, at_sr, strat.candlestick)
    p3_scores = score_p3(p3_s, strat.p3)
    p5_scores = score_p5(p5_s, strat.p5)
    vol_scores = score_volume(df["close"], df["open"], df["volume"], candle_s, strat.volume)
    ema_scores = score_ema(df["close"], ema_df, strat.ema)
    sr_scores = score_sr(df["close"], df["high"], df["low"], df["volume"], sr_df, strat.sr)
    macd_scores = score_macd(df["close"], macd_df, strat.macd)
    rsi_scores = score_rsi(rsi_s, strat.rsi)

    # ── Assemble auditable output ─────────────────────────────────────────────
    results: list[dict] = []
    for i, (idx, _) in enumerate(df.iterrows()):
        regime = {
            "long_allowed": bool(regime_df["long_allowed"].iat[i]),
            "short_allowed": bool(regime_df["short_allowed"].iat[i]),
        }
        sub_scores = {
            "candlestick": float(cs_scores.iat[i]),
            "p3":          float(p3_scores.iat[i]),
            "p5":          float(p5_scores.iat[i]),
            "volume":      float(vol_scores.iat[i]),
            "ema":         float(ema_scores.iat[i]),
            "sr":          float(sr_scores.iat[i]),
            "macd":        float(macd_scores.iat[i]),
            "rsi":         float(rsi_scores.iat[i]),
        }
        bar = score_bar(sub_scores, strat.weights, regime, strat.thresholds)
        bar["date"] = str(idx.date()) if hasattr(idx, "date") else str(idx)
        bar["strategy"] = strategy
        results.append(bar)

    return results

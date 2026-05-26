"""Pre-compute raw indicators and default component scores for all symbols.

Strategy: compute everything over the FULL date range once.  For each optimisation
trial we slice the results to the in-sample (or holdout / walk-forward) window and
re-apply only the parts that changed (weights, thresholds, or scoring tables).

Key invariant: scoring functions are called over the full period so rolling windows
(e.g. 30-bar volume average, 20-bar range average in S/R) have full historical context
at every bar — even at the first bar of the in-sample window.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from backend.app.config import AppConfig
from backend.app.indicators.atr import compute_atr
from backend.app.indicators.candlestick import detect_candlestick_pattern
from backend.app.indicators.ema import compute_emas
from backend.app.indicators.macd import compute_macd
from backend.app.indicators.pivots import detect_p3_pattern, detect_p5_pattern
from backend.app.indicators.rsi import compute_rsi
from backend.app.indicators.support_resistance import compute_sr_levels
from backend.app.scoring.candlestick import score_candlestick
from backend.app.scoring.composite import score_bar
from backend.app.scoring.ema import score_ema
from backend.app.scoring.macd import score_macd
from backend.app.scoring.p3 import score_p3
from backend.app.scoring.p5 import score_p5
from backend.app.scoring.regime import compute_regime
from backend.app.scoring.rsi import score_rsi
from backend.app.scoring.support_resistance import score_sr
from backend.app.scoring.volume import score_volume

logger = logging.getLogger(__name__)

DataFetcher = Callable[[str, date, date], pd.DataFrame]

_MIN_BARS = 50


@dataclass
class PrecomputedSymbol:
    sym: str
    dates: list[date]                # sorted, all bars in the full range
    bars: dict[date, dict]           # date → {open, high, low, close}
    atr: dict[date, float]           # for ATR stop sizing

    # Full-period raw indicator Series (DatetimeIndex aligned)
    close_s: pd.Series
    open_s: pd.Series
    high_s: pd.Series
    low_s: pd.Series
    volume_s: pd.Series
    date_index: pd.DatetimeIndex

    ema_df: pd.DataFrame
    macd_df: pd.DataFrame
    rsi_s: pd.Series
    candle_s: pd.Series              # pattern-name strings
    p3_s: pd.Series
    p5_s: pd.Series
    sr_df: pd.DataFrame
    at_sr: pd.Series                 # boolean
    regime_df: pd.DataFrame          # columns: long_allowed, short_allowed

    # Pre-computed component scores with DEFAULT scoring tables.
    # Reused as-is for Phase-1 (weights-only) trials.
    default_scores: dict[str, pd.Series] = field(default_factory=dict)

    # date → position in full dates list (built lazily)
    _date_to_pos: dict[date, int] = field(default_factory=dict, repr=False)

    def date_pos(self, d: date) -> int | None:
        if not self._date_to_pos:
            self._date_to_pos = {dd: i for i, dd in enumerate(self.dates)}
        return self._date_to_pos.get(d)

    def dates_in_range(self, start: date, end: date) -> list[date]:
        return [d for d in self.dates if start <= d <= end]


def precompute_symbols(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    include_scoring_tables: bool = False,
) -> dict[str, PrecomputedSymbol]:
    """Fetch data and pre-compute indicators + default scores for every symbol.

    ``include_scoring_tables=False`` (Phase-1 mode): stores pre-computed component
    scores with the default scoring tables.  Per-trial cost is minimal: just re-weight.

    ``include_scoring_tables=True`` (Phase-2 mode): also stores raw indicator Series
    so scoring functions can be re-run with new tables per trial.
    """
    strat = cfg.get_strategy("long")
    result: dict[str, PrecomputedSymbol] = {}

    for sym in symbols:
        try:
            df = data_fetcher(sym, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] fetch failed: %s — skipping", sym, exc)
            continue
        if len(df) < _MIN_BARS:
            logger.debug("[%s] only %d bars — skipping", sym, len(df))
            continue

        # ── Indicators ──────────────────────────────────────────────────────
        ema_df   = compute_emas(df, strat.ema.periods, strat.regime.slope_lookback)
        macd_df  = compute_macd(df, strat.macd.fast, strat.macd.slow, strat.macd.signal)
        rsi_s    = compute_rsi(df, strat.rsi.period)
        atr_s    = compute_atr(df, cfg.backtest.atr_period)
        candle_s = detect_candlestick_pattern(
            df,
            long_candle_body_pct=strat.candlestick.long_candle_body_pct,
            hammer_wick_mult=strat.candlestick.hammer_wick_mult,
            doji_body_pct=strat.candlestick.doji_body_pct,
        )
        p3_s    = detect_p3_pattern(df)
        p5_s    = detect_p5_pattern(df)
        sr_df   = compute_sr_levels(df, strat.sr.cluster_pct)
        regime_df = compute_regime(df["close"], ema_df, strat.regime)

        tol = 0.005
        support    = sr_df["support_level"]
        resistance = sr_df["resistance_level"]
        at_sr = (
            (support.notna() & ((df["low"] - support).abs() / support <= tol))
            | (resistance.notna() & ((df["high"] - resistance).abs() / resistance <= tol))
        )

        # ── Per-bar dicts ───────────────────────────────────────────────────
        dates: list[date] = [
            idx.date() if hasattr(idx, "date") else idx for idx in df.index
        ]
        bars: dict[date, dict] = {}
        atr_vals: dict[date, float] = {}
        for i, d in enumerate(dates):
            bars[d] = {
                "open":  float(df.iloc[i]["open"]),
                "high":  float(df.iloc[i]["high"]),
                "low":   float(df.iloc[i]["low"]),
                "close": float(df.iloc[i]["close"]),
            }
            atr_vals[d] = float(atr_s.iat[i]) if not pd.isna(atr_s.iat[i]) else 0.0

        # ── Default component scores (full period, default scoring tables) ─
        default_scores: dict[str, pd.Series] = {}
        cs_scores   = score_candlestick(candle_s, at_sr, strat.candlestick)
        p3_scores   = score_p3(p3_s, strat.p3)
        p5_scores   = score_p5(p5_s, strat.p5)
        vol_scores  = score_volume(df["close"], df["open"], df["volume"], candle_s, strat.volume)
        ema_scores  = score_ema(df["close"], ema_df, strat.ema)
        sr_scores   = score_sr(df["close"], df["high"], df["low"], df["volume"], sr_df, strat.sr)
        macd_scores = score_macd(df["close"], macd_df, strat.macd)
        rsi_scores  = score_rsi(rsi_s, strat.rsi)

        default_scores = {
            "candlestick": cs_scores,
            "p3":          p3_scores,
            "p5":          p5_scores,
            "volume":      vol_scores,
            "ema":         ema_scores,
            "sr":          sr_scores,
            "macd":        macd_scores,
            "rsi":         rsi_scores,
        }

        result[sym] = PrecomputedSymbol(
            sym=sym, dates=dates, bars=bars, atr=atr_vals,
            close_s=df["close"], open_s=df["open"],
            high_s=df["high"], low_s=df["low"], volume_s=df["volume"],
            date_index=df.index,
            ema_df=ema_df, macd_df=macd_df, rsi_s=rsi_s,
            candle_s=candle_s, p3_s=p3_s, p5_s=p5_s,
            sr_df=sr_df, at_sr=at_sr, regime_df=regime_df,
            default_scores=default_scores,
        )

    logger.info("Pre-computed %d of %d symbols", len(result), len(symbols))
    return result


def recompute_scores(pc: PrecomputedSymbol, strat) -> dict[str, pd.Series]:
    """Re-run all scoring functions with a new StrategyConfig (Phase-2 trials)."""
    return {
        "candlestick": score_candlestick(pc.candle_s, pc.at_sr, strat.candlestick),
        "p3":          score_p3(pc.p3_s, strat.p3),
        "p5":          score_p5(pc.p5_s, strat.p5),
        "volume":      score_volume(pc.close_s, pc.open_s, pc.volume_s, pc.candle_s, strat.volume),
        "ema":         score_ema(pc.close_s, pc.ema_df, strat.ema),
        "sr":          score_sr(pc.close_s, pc.high_s, pc.low_s, pc.volume_s, pc.sr_df, strat.sr),
        "macd":        score_macd(pc.close_s, pc.macd_df, strat.macd),
        "rsi":         score_rsi(pc.rsi_s, strat.rsi),
    }

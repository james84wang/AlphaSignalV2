"""Loads config.yaml into typed Pydantic models and validates weights sum to 100."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator


# ── Leaf models ────────────────────────────────────────────────────────────────

class Thresholds(BaseModel):
    strong_buy: float
    buy: float
    sell: float
    strong_sell: float


class Weights(BaseModel):
    candlestick: float
    p3: float
    p5: float
    volume: float
    ema: float
    sr: float
    macd: float
    rsi: float

    @model_validator(mode="after")
    def weights_must_sum_to_100(self) -> "Weights":
        total = (
            self.candlestick + self.p3 + self.p5 + self.volume
            + self.ema + self.sr + self.macd + self.rsi
        )
        if abs(total - 100) > 1e-6:
            raise ValueError(
                f"Component weights must sum to 100, but got {total}. "
                "Check config.yaml [weights] section."
            )
        return self


class RegimeConfig(BaseModel):
    ema_period: int
    slope_lookback: int


class CandlestickScores(BaseModel):
    long_bullish_candle: float
    green_hammer: float
    inverted_green_hammer: float
    bullish_spinning_top: float
    bullish_doji: float
    bearish_doji: float
    bearish_spinning_top: float
    inverted_red_hammer: float
    red_hammer: float
    long_bearish_candle: float
    no_pattern: float


class CandlestickConfig(BaseModel):
    long_candle_body_pct: float
    hammer_wick_mult: float
    doji_body_pct: float
    sr_context_multiplier: float
    scores: CandlestickScores


class P3Scores(BaseModel):
    bullish_reversal_at_support: float
    bullish_breakout_above_resistance: float
    continuation_up: float
    no_pattern: float
    continuation_down: float
    bearish_breakdown_below_support: float
    bearish_reversal_at_resistance: float


class P3Config(BaseModel):
    window: int
    scores: P3Scores


class P5Scores(BaseModel):
    major_bullish_reversal: float
    bullish_trend_confirmation: float
    range_bound: float
    bearish_trend_confirmation: float
    major_bearish_reversal: float


class P5Config(BaseModel):
    window: int
    scores: P5Scores


class VolumeBucket(BaseModel):
    rv_min: Optional[float]
    rv_max: Optional[float]
    score: float


class VolumeConfig(BaseModel):
    avg_period: int
    bullish_buckets: list[VolumeBucket]


class EmaStackingScores(BaseModel):
    full_bull: float
    above_3: float
    above_2: float
    below_3: float
    full_bear: float


class EmaCrossScores(BaseModel):
    cross_above_200: float
    cross_above_100: float
    cross_above_50: float
    cross_above_20: float
    cross_below_20: float
    cross_below_50: float
    cross_below_100: float
    cross_below_200: float


class EmaConfig(BaseModel):
    periods: list[int]
    stacking_scores: EmaStackingScores
    cross_scores: EmaCrossScores


class SrScores(BaseModel):
    strong_bounce_off_support: float
    breakout_above_resistance: float
    approach_support: float
    no_interaction: float
    approach_resistance: float
    strong_rejection_off_resistance: float
    breakdown_below_support: float


class SrConfig(BaseModel):
    cluster_pct: float
    breakout_volume_mult: float
    scores: SrScores


class MacdMicroSignals(BaseModel):
    golden_cross: float
    death_cross: float
    macd_above_zero: float
    macd_below_zero: float
    histogram_green_expanding: float
    histogram_green_contracting: float
    histogram_red_expanding: float
    histogram_red_contracting: float
    bullish_divergence: float
    bearish_divergence: float


class MacdConfig(BaseModel):
    fast: int
    slow: int
    signal: int
    micro_signals: MacdMicroSignals


class RsiScores(BaseModel):
    crosses_up_30: float
    below_30_rising: float
    below_30_falling: float
    between_30_50_rising: float
    between_30_50_falling: float
    between_50_70_rising: float
    between_50_70_falling: float
    above_70_rising: float
    above_70_falling: float
    crosses_down_70: float


class RsiConfig(BaseModel):
    period: int
    scores: RsiScores


class UniverseConfig(BaseModel):
    default: str
    timeframe: str
    watchlist_file: str


class RiskConfig(BaseModel):
    stop_loss_method: str
    stop_loss_atr_mult: float
    stop_loss_atr_period: int
    position_size_pct: float
    trail_stop_atr_mult: float
    max_concurrent_positions: int
    reentry_cooldown_bars: int
    earnings_blackout_bars: int


# ── Root model ─────────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    thresholds: Thresholds
    weights: Weights
    regime: RegimeConfig
    candlestick: CandlestickConfig
    p3: P3Config
    p5: P5Config
    volume: VolumeConfig
    ema: EmaConfig
    sr: SrConfig
    macd: MacdConfig
    rsi: RsiConfig
    universe: UniverseConfig
    risk: RiskConfig

    @property
    def weights_valid(self) -> bool:
        """True when weight validation already passed (it always will if we got here)."""
        return True


_config: AppConfig | None = None


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load and validate config.yaml. Cached after the first call."""
    global _config
    if _config is not None:
        return _config

    if path is None:
        # Resolve relative to the repo root (two levels up from this file).
        path = Path(__file__).resolve().parents[2] / "config.yaml"

    with open(path) as fh:
        raw = yaml.safe_load(fh)

    _config = AppConfig.model_validate(raw)
    return _config

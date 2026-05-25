"""Loads config.yaml into typed Pydantic models and validates weights sum to 100."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

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


class BacktestConfig(BaseModel):
    start_years_back: int
    initial_fund: float = 100000.0
    slippage_pct: float = 0.001
    commission_per_trade: float = 1.0
    # MOD-F: Platform fee model
    fee_per_share: float = 0.005
    fee_min: float = 1.00
    fee_max_pct_of_trade: float = 0.01
    # MOD-F: Fixed-fractional sizing
    position_size_pct: float = 0.08
    position_size_min: float = 2000.0
    # MOD-F: ATR stop (backtest-specific; separate from risk.stop_loss_atr_mult)
    atr_stop_multiple: float = 1.5
    atr_period: int = 14
    # MOD-F: Portfolio constraints
    max_concurrent_positions: int = 15
    per_name_cap_pct: float = 0.30
    top_n: int = 10
    # MOD-F: Benchmark
    benchmark_symbol: str = "QQQ"
    risk_free_rate: float = 0.0

    @property
    def initial_account(self) -> float:
        """Backward-compat alias for initial_fund."""
        return self.initial_fund


# ── Per-strategy profile ───────────────────────────────────────────────────────

class StrategyConfig(BaseModel):
    """All tunable parameters for one strategy profile (long or short)."""

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

    @property
    def weights_valid(self) -> bool:
        return True


# ── Root model ─────────────────────────────────────────────────────────────────

class StrategiesMap(BaseModel):
    long: StrategyConfig
    short: StrategyConfig


class AppConfig(BaseModel):
    strategies: StrategiesMap
    universe: UniverseConfig
    risk: RiskConfig
    backtest: BacktestConfig

    @property
    def weights_valid(self) -> bool:
        """True when weight validation already passed for both profiles."""
        return True

    def get_strategy(self, name: Literal["long", "short"]) -> StrategyConfig:
        """Return the named strategy profile."""
        if name == "long":
            return self.strategies.long
        if name == "short":
            return self.strategies.short
        raise ValueError(f"Unknown strategy name {name!r}; must be 'long' or 'short'")

    # Convenience shims so old call-sites that read cfg.weights / cfg.thresholds
    # etc. keep working — they get the long profile by default.
    @property
    def weights(self) -> Weights:
        return self.strategies.long.weights

    @property
    def thresholds(self) -> Thresholds:
        return self.strategies.long.thresholds

    @property
    def regime(self) -> RegimeConfig:
        return self.strategies.long.regime

    @property
    def candlestick(self) -> CandlestickConfig:
        return self.strategies.long.candlestick

    @property
    def p3(self) -> P3Config:
        return self.strategies.long.p3

    @property
    def p5(self) -> P5Config:
        return self.strategies.long.p5

    @property
    def volume(self) -> VolumeConfig:
        return self.strategies.long.volume

    @property
    def ema(self) -> EmaConfig:
        return self.strategies.long.ema

    @property
    def sr(self) -> SrConfig:
        return self.strategies.long.sr

    @property
    def macd(self) -> MacdConfig:
        return self.strategies.long.macd

    @property
    def rsi(self) -> RsiConfig:
        return self.strategies.long.rsi


_config: AppConfig | None = None


def reset_config() -> None:
    """Clear the cached config so the next load_config() re-reads config.yaml."""
    global _config
    _config = None


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

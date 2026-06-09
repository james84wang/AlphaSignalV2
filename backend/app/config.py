"""Loads config.yaml into typed Pydantic models for the Hidden-Divergence
Confluence strategy (profile name: "hidden_div", long-only).

Config-key naming: every leaf key in config.yaml maps **1:1 to the TradingView
Pine input** (e.g. ``wMacd``, ``entryThreshold``, ``lbR``) via pydantic aliases,
so the strategy can be exported to PineScript later without guesswork. Python
attribute names stay descriptive (``macd_hidden_bull``) — the alias is only the
on-disk / Pine name. See the mapping table in docs/ABOUT.md (Strategy Details).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

PROFILE = "hidden_div"

# ── shared model config: accept both the Pine alias and the python field name ──
_CFG = ConfigDict(populate_by_name=True)


# ── Indicator / regime parameter blocks ─────────────────────────────────────────

class RegimeConfig(BaseModel):
    model_config = _CFG
    ema_fast: int = Field(alias="emaFast")          # fast EMA period (default 50)
    ema_slow: int = Field(alias="emaSlow")          # slow EMA period (default 200)
    slope_lookback: int = Field(alias="slopeLook")  # bars used to test "EMA rising"


class PivotsConfig(BaseModel):
    model_config = _CFG
    left: int = Field(alias="lbL")                  # left bars for a swing pivot
    right: int = Field(alias="lbR")                 # right bars (also confirmation lag)
    min_bars: int = Field(alias="minPivGap")        # min spacing between divergence pivots
    max_bars: int = Field(alias="maxPivGap")        # max spacing between divergence pivots


class MacdConfig(BaseModel):
    model_config = _CFG
    fast: int = Field(alias="macdFast")
    slow: int = Field(alias="macdSlow")
    signal: int = Field(alias="macdSig")


class RsiConfig(BaseModel):
    model_config = _CFG
    period: int = Field(alias="rsiLen")
    zone_low: float = Field(alias="rsiZoneLo")      # RSI pullback "buy zone" lower bound
    zone_high: float = Field(alias="rsiZoneHi")     # RSI pullback "buy zone" upper bound


class DemarkConfig(BaseModel):
    model_config = _CFG
    setup: int = Field(alias="tdSetup")             # bars in a TD setup (default 9)
    countdown: int = Field(alias="tdCountdown")     # bars in a TD countdown (default 13)
    setup_lookback: int = Field(alias="tdFlipLook")     # setup close-vs-close lookback (4)
    countdown_lookback: int = Field(alias="tdCountLook")  # countdown close-vs-h/l lookback (2)


# ── Confluence weights & sides ──────────────────────────────────────────────────

class EntryWeights(BaseModel):
    model_config = _CFG
    macd_hidden_bull: float = Field(alias="wMacd")
    rsi_hidden_bull: float = Field(alias="wRsi")
    rsi_zone: float = Field(alias="wZone")
    demark_td9_buy: float = Field(alias="wTd9")

    @field_validator("*")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Entry weights must be non-negative")
        return v


class ExitWeights(BaseModel):
    model_config = _CFG
    macd_regular_bear: float = Field(alias="wMacdX")
    rsi_regular_bear: float = Field(alias="wRsiX")
    demark_td13_sell: float = Field(alias="wTd13")
    demark_td9_sell: float = Field(alias="wTd9X")

    @field_validator("*")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Exit weights must be non-negative")
        return v


class EntryConfig(BaseModel):
    model_config = _CFG
    threshold: float = Field(alias="entryThreshold")   # entry score ≥ this fires a BUY (65)
    conf_window: int = Field(alias="confWin")          # entry confluence window + cooldown (10)
    weights: EntryWeights


class ExitConfig(BaseModel):
    model_config = _CFG
    threshold: float = Field(alias="exitThreshold")    # exit score ≥ this fires a SELL (35)
    conf_window: int = Field(alias="confWinX")         # exit confluence window + cooldown (5)
    weights: ExitWeights


# ── Per-strategy profile ────────────────────────────────────────────────────────

class StrategyConfig(BaseModel):
    """All tunable parameters for the hidden_div confluence strategy."""

    regime: RegimeConfig
    pivots: PivotsConfig
    macd: MacdConfig
    rsi: RsiConfig
    demark: DemarkConfig
    entry: EntryConfig
    exit: ExitConfig


# ── Top-level sections ──────────────────────────────────────────────────────────

class UniverseConfig(BaseModel):
    default: str
    timeframe: str
    watchlist_file: str
    watchlists: list[str] = ["Watchlist"]


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
    fee_per_share: float = 0.005
    fee_min: float = 1.00
    fee_max_pct_of_trade: float = 0.01
    position_size_pct: float = 0.08
    position_size_min: float = 2000.0
    atr_stop_multiple: float = 1.5
    atr_period: int = 14
    max_concurrent_positions: int = 15
    per_name_cap_pct: float = 0.30
    top_n: int = 10
    benchmark_symbol: str = "QQQ"
    risk_free_rate: float = 0.0

    @property
    def initial_account(self) -> float:
        """Backward-compat alias for initial_fund."""
        return self.initial_fund


class StrategiesMap(BaseModel):
    hidden_div: StrategyConfig


class AppConfig(BaseModel):
    strategies: StrategiesMap
    universe: UniverseConfig
    risk: RiskConfig
    backtest: BacktestConfig

    @property
    def weights_valid(self) -> bool:
        """Retained for the /health endpoint; always True under the new schema."""
        return True

    def get_strategy(self, name: Literal["hidden_div"] = PROFILE) -> StrategyConfig:
        """Return the hidden_div strategy profile (the only profile)."""
        if name != PROFILE:
            raise ValueError(f"Unknown strategy name {name!r}; only {PROFILE!r} is supported")
        return self.strategies.hidden_div


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
        path = Path(__file__).resolve().parents[2] / "config.yaml"

    with open(path) as fh:
        raw = yaml.safe_load(fh)

    _config = AppConfig.model_validate(raw)
    return _config

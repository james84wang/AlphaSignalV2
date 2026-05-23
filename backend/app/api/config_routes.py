"""Per-strategy config API: GET/PUT /api/config/{strategy}."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from backend.app.config import load_config, reset_config
from backend.app.db.models import config_hash

router = APIRouter(prefix="/api/config", tags=["config"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_VERSIONS_PATH = _REPO_ROOT.parent / "data" / "config_versions.jsonl"

StrategyName = Literal["long", "short"]


# ── Request models ────────────────────────────────────────────────────────────

class WeightsUpdate(BaseModel):
    candlestick: float
    p3: float
    p5: float
    volume: float
    ema: float
    sr: float
    macd: float
    rsi: float

    @model_validator(mode="after")
    def must_sum_to_100(self) -> "WeightsUpdate":
        total = (
            self.candlestick + self.p3 + self.p5 + self.volume
            + self.ema + self.sr + self.macd + self.rsi
        )
        if abs(total - 100) > 1e-4:
            raise ValueError(f"Weights must sum to 100, got {total:.6f}")
        for name in ("candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"):
            if getattr(self, name) < 0:
                raise ValueError(f"Weight '{name}' must be non-negative")
        return self


class ThresholdsUpdate(BaseModel):
    strong_buy: float
    buy: float
    sell: float
    strong_sell: float

    @model_validator(mode="after")
    def must_be_ordered(self) -> "ThresholdsUpdate":
        if not (self.strong_sell < self.sell < 0 < self.buy < self.strong_buy):
            raise ValueError(
                "Thresholds must satisfy: strong_sell < sell < 0 < buy < strong_buy"
            )
        return self


class ScoringTablesUpdate(BaseModel):
    """Optional per-indicator score maps. Only tables present are updated."""
    candlestick: dict[str, float] | None = None
    p3: dict[str, float] | None = None
    p5: dict[str, float] | None = None
    ema_stacking: dict[str, float] | None = None
    ema_cross: dict[str, float] | None = None
    sr: dict[str, float] | None = None
    macd: dict[str, float] | None = None
    rsi: dict[str, float] | None = None

    @model_validator(mode="after")
    def scores_in_range(self) -> "ScoringTablesUpdate":
        for field in ("candlestick", "p3", "p5", "ema_stacking", "ema_cross", "sr", "macd", "rsi"):
            table = getattr(self, field)
            if table is None:
                continue
            for key, val in table.items():
                if not (-100 <= val <= 100):
                    raise ValueError(
                        f"{field}.{key} = {val} is out of range [-100, 100]"
                    )
        return self


class ProfileUpdate(BaseModel):
    """Full or partial profile update. weights is always required (sum=100)."""
    weights: WeightsUpdate
    thresholds: ThresholdsUpdate | None = None
    scoring_tables: ScoringTablesUpdate | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{strategy}")
def get_config(strategy: StrategyName) -> dict:
    """Return the strategy configuration for the given profile as a JSON object."""
    cfg = load_config(_CONFIG_PATH)
    strat = cfg.get_strategy(strategy)
    return strat.model_dump()


@router.put("/{strategy}")
def put_config(strategy: StrategyName, body: ProfileUpdate) -> dict:
    """Update weights, and optionally thresholds and scoring tables, for one strategy profile."""
    with open(_CONFIG_PATH) as fh:
        raw = yaml.safe_load(fh)

    strat = raw["strategies"][strategy]

    # ── weights ──
    old_weights = dict(strat.get("weights", {}))
    strat["weights"] = body.weights.model_dump()

    # ── thresholds (optional) ──
    if body.thresholds is not None:
        strat["thresholds"] = body.thresholds.model_dump()

    # ── scoring tables (optional, per-table) ──
    if body.scoring_tables is not None:
        st = body.scoring_tables
        if st.candlestick is not None:
            strat["candlestick"]["scores"] = dict(st.candlestick)
        if st.p3 is not None:
            strat["p3"]["scores"] = dict(st.p3)
        if st.p5 is not None:
            strat["p5"]["scores"] = dict(st.p5)
        if st.ema_stacking is not None:
            strat["ema"]["stacking_scores"] = dict(st.ema_stacking)
        if st.ema_cross is not None:
            strat["ema"]["cross_scores"] = dict(st.ema_cross)
        if st.sr is not None:
            strat["sr"]["scores"] = dict(st.sr)
        if st.macd is not None:
            strat["macd"]["micro_signals"] = dict(st.macd)
        if st.rsi is not None:
            strat["rsi"]["scores"] = dict(st.rsi)

    try:
        with open(_CONFIG_PATH, "w") as fh:
            yaml.safe_dump(raw, fh, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        raise HTTPException(500, detail=f"Failed to write config.yaml: {exc}")

    reset_config()

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "timestamp": now,
        "strategy": strategy,
        "old_weights": old_weights,
        "new_weights": body.weights.model_dump(),
        "thresholds_updated": body.thresholds is not None,
        "scoring_tables_updated": body.scoring_tables is not None,
    }
    try:
        _VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_VERSIONS_PATH, "a") as fh:
            fh.write(json.dumps(snapshot) + "\n")
    except OSError:
        pass

    new_hash = config_hash(_CONFIG_PATH)
    return {
        "ok": True,
        "strategy": strategy,
        "weights": body.weights.model_dump(),
        "thresholds_updated": body.thresholds is not None,
        "scoring_tables_updated": body.scoring_tables is not None,
        "config_hash": new_hash,
        "version_saved_at": now,
    }

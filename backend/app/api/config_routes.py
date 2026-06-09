"""Strategy config API: GET/PUT /api/config/long.

Exposes the long-only Hidden-Divergence Confluence parameters. The user can tune
each entry/exit component weight, the buy (entry) and sell (exit) thresholds, the
confluence windows, and the underlying indicator parameters.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator, model_validator

from backend.app.config import AppConfig, StrategyConfig, load_config, reset_config
from backend.app.db.models import config_hash
from backend.app.export.pine import generate_pine

router = APIRouter(prefix="/api/config", tags=["config"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_VERSIONS_PATH = _REPO_ROOT.parent / "data" / "config_versions.jsonl"

StrategyName = Literal["hidden_div"]


# ── Request models ────────────────────────────────────────────────────────────

class EntryWeightsUpdate(BaseModel):
    macd_hidden_bull: float
    rsi_hidden_bull: float
    rsi_zone: float
    demark_td9_buy: float

    @field_validator("*")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("weights must be non-negative")
        return v


class ExitWeightsUpdate(BaseModel):
    demark_td13_sell: float
    macd_regular_bear: float
    rsi_regular_bear: float
    demark_td9_sell: float

    @field_validator("*")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("weights must be non-negative")
        return v


class SideUpdate(BaseModel):
    threshold: float
    conf_window: int

    @model_validator(mode="after")
    def _ranges(self) -> "SideUpdate":
        if not (0 <= self.threshold <= 300):
            raise ValueError("threshold must be between 0 and 300")
        if self.conf_window < 1:
            raise ValueError("conf_window must be >= 1")
        return self


class EntryUpdate(SideUpdate):
    weights: EntryWeightsUpdate


class ExitUpdate(SideUpdate):
    weights: ExitWeightsUpdate


class ParamsUpdate(BaseModel):
    """Optional advanced indicator parameters. Only blocks present are written."""
    regime: dict[str, float] | None = None
    pivots: dict[str, float] | None = None
    macd: dict[str, float] | None = None
    rsi: dict[str, float] | None = None
    demark: dict[str, float] | None = None


class ProfileUpdate(BaseModel):
    entry: EntryUpdate
    exit: ExitUpdate
    params: ParamsUpdate | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{strategy}")
def get_config(strategy: StrategyName) -> dict:
    """Return the long strategy configuration as a JSON object."""
    cfg = load_config(_CONFIG_PATH)
    return cfg.get_strategy(strategy).model_dump()


@router.get("/{strategy}/pine", response_class=PlainTextResponse)
def get_pine(strategy: StrategyName) -> PlainTextResponse:
    """Download the strategy as a TradingView Pine Script (v6).

    The script is generated from the **currently saved** config, so every input
    default matches your tuned weights/thresholds and the Python backtest.
    """
    cfg = load_config(_CONFIG_PATH)
    pine = generate_pine(cfg.get_strategy(strategy))
    return PlainTextResponse(
        pine,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="hidden_div_confluence_uptrend.pine"',
        },
    )


@router.put("/{strategy}")
def put_config(strategy: StrategyName, body: ProfileUpdate) -> dict:
    """Update entry/exit weights + thresholds (and optional indicator params)."""
    with open(_CONFIG_PATH) as fh:
        raw = yaml.safe_load(fh)

    # Work in descriptive field names internally, then write back with the Pine
    # aliases so config.yaml stays 1:1 with the TradingView inputs.
    strat_d = AppConfig.model_validate(raw).get_strategy(strategy).model_dump()
    old_entry = dict(strat_d.get("entry", {}))

    strat_d["entry"] = {
        "threshold": body.entry.threshold,
        "conf_window": body.entry.conf_window,
        "weights": body.entry.weights.model_dump(),
    }
    strat_d["exit"] = {
        "threshold": body.exit.threshold,
        "conf_window": body.exit.conf_window,
        "weights": body.exit.weights.model_dump(),
    }

    if body.params is not None:
        for block in ("regime", "pivots", "macd", "rsi", "demark"):
            update = getattr(body.params, block)
            if update is not None:
                strat_d[block].update(update)

    # Validate the merged profile, then dump with Pine alias keys for the file.
    raw["strategies"][strategy] = StrategyConfig.model_validate(strat_d).model_dump(by_alias=True)
    strat = strat_d  # for the response/snapshot below (descriptive names)

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
        "old_entry": old_entry,
        "new_entry": strat["entry"],
        "new_exit": strat["exit"],
        "params_updated": body.params is not None,
    }
    try:
        _VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_VERSIONS_PATH, "a") as fh:
            fh.write(json.dumps(snapshot) + "\n")
    except OSError:
        pass

    return {
        "ok": True,
        "strategy": strategy,
        "entry": strat["entry"],
        "exit": strat["exit"],
        "params_updated": body.params is not None,
        "config_hash": config_hash(_CONFIG_PATH),
        "version_saved_at": now,
    }

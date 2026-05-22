"""GET /api/config and PUT /api/config — read and update strategy configuration."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from backend.app.config import load_config, reset_config
from backend.app.db.models import config_hash

router = APIRouter(prefix="/api/config", tags=["config"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
_VERSIONS_PATH = _REPO_ROOT.parent / "data" / "config_versions.jsonl"


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


@router.get("")
def get_config() -> dict:
    """Return the current strategy configuration as a JSON object."""
    cfg = load_config(_CONFIG_PATH)
    return cfg.model_dump()


@router.put("")
def put_config(body: WeightsUpdate) -> dict:
    """Update component weights, validate sum=100, write to config.yaml, version it."""
    with open(_CONFIG_PATH) as fh:
        raw = yaml.safe_load(fh)

    # Snapshot old weights for versioning.
    old_weights = dict(raw.get("weights", {}))

    # Apply new weights.
    new_weights = body.model_dump()
    raw["weights"] = new_weights

    try:
        with open(_CONFIG_PATH, "w") as fh:
            yaml.safe_dump(raw, fh, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        raise HTTPException(500, detail=f"Failed to write config.yaml: {exc}")

    # Clear the config cache so the next load_config() picks up the new file.
    reset_config()

    # Persist a versioned snapshot.
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "timestamp": now,
        "old_weights": old_weights,
        "new_weights": new_weights,
    }
    try:
        _VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_VERSIONS_PATH, "a") as fh:
            fh.write(json.dumps(snapshot) + "\n")
    except OSError:
        pass  # Non-fatal — don't block the response.

    new_hash = config_hash(_CONFIG_PATH)
    return {
        "ok": True,
        "weights": new_weights,
        "config_hash": new_hash,
        "version_saved_at": now,
    }

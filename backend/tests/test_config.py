"""Tests for config loading and validation (Hidden-Divergence Confluence schema)."""
from pathlib import Path

import pytest

from backend.app.config import AppConfig, EntryWeights, StrategyConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_config_loads():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert isinstance(cfg, AppConfig)


def test_long_profile_present():
    cfg = load_config(REPO_ROOT / "config.yaml")
    strat = cfg.get_strategy("hidden_div")
    assert isinstance(strat, StrategyConfig)


def test_entry_and_exit_weights():
    cfg = load_config(REPO_ROOT / "config.yaml")
    strat = cfg.get_strategy("hidden_div")
    # All four entry + four exit components exist and are non-negative.
    for name in ("macd_hidden_bull", "rsi_hidden_bull", "rsi_zone", "demark_td9_buy"):
        assert getattr(strat.entry.weights, name) >= 0
    for name in ("demark_td13_sell", "macd_regular_bear", "rsi_regular_bear", "demark_td9_sell"):
        assert getattr(strat.exit.weights, name) >= 0
    assert strat.entry.threshold > 0
    assert strat.exit.threshold > 0


def test_regime_params():
    cfg = load_config(REPO_ROOT / "config.yaml")
    reg = cfg.get_strategy("hidden_div").regime
    assert reg.ema_fast < reg.ema_slow  # fast EMA shorter than slow EMA


def test_watchlists_configured():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert "Watchlist" in cfg.universe.watchlists
    assert len(cfg.universe.watchlists) >= 1


def test_negative_weight_rejected():
    with pytest.raises(ValueError):
        EntryWeights.model_validate(
            {"macd_hidden_bull": -5, "rsi_hidden_bull": 35, "rsi_zone": 20, "demark_td9_buy": 10}
        )


def test_get_strategy_unknown_name_raises():
    cfg = load_config(REPO_ROOT / "config.yaml")
    with pytest.raises(ValueError, match="Unknown strategy"):
        cfg.get_strategy("short")  # type: ignore[arg-type]


def test_health_endpoint():
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

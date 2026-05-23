"""Tests for config loading and validation (implements spec §2.2 weight constraint)."""
from pathlib import Path

import pytest

from backend.app.config import AppConfig, StrategyConfig, Weights, load_config


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_weights_sum_to_100():
    cfg = load_config(REPO_ROOT / "config.yaml")
    total = sum([
        cfg.weights.candlestick, cfg.weights.p3, cfg.weights.p5,
        cfg.weights.volume, cfg.weights.ema, cfg.weights.sr,
        cfg.weights.macd, cfg.weights.rsi,
    ])
    assert abs(total - 100) < 1e-6, f"Weights sum to {total}, expected 100"


def test_weights_valid_flag():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.weights_valid is True


def test_tampered_weights_rejected():
    """Config with weights ≠ 100 must raise ValueError."""
    bad_raw = {
        "candlestick": 99, "p3": 8, "p5": 12, "volume": 10,
        "ema": 15, "sr": 15, "macd": 18, "rsi": 10,
    }
    with pytest.raises(ValueError, match="sum to 100"):
        Weights.model_validate(bad_raw)


def test_health_endpoint():
    """Smoke-test that the FastAPI health route returns 200 with expected keys."""
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["weights_valid"] is True


# ── Strategy profile tests ─────────────────────────────────────────────────────

def test_both_profiles_present():
    cfg = load_config(REPO_ROOT / "config.yaml")
    long_strat = cfg.get_strategy("long")
    short_strat = cfg.get_strategy("short")
    assert isinstance(long_strat, StrategyConfig)
    assert isinstance(short_strat, StrategyConfig)


def test_long_profile_weights_sum_to_100():
    cfg = load_config(REPO_ROOT / "config.yaml")
    w = cfg.get_strategy("long").weights
    total = w.candlestick + w.p3 + w.p5 + w.volume + w.ema + w.sr + w.macd + w.rsi
    assert abs(total - 100) < 1e-6


def test_short_profile_weights_sum_to_100():
    cfg = load_config(REPO_ROOT / "config.yaml")
    w = cfg.get_strategy("short").weights
    total = w.candlestick + w.p3 + w.p5 + w.volume + w.ema + w.sr + w.macd + w.rsi
    assert abs(total - 100) < 1e-6


def test_get_strategy_unknown_name_raises():
    cfg = load_config(REPO_ROOT / "config.yaml")
    with pytest.raises(ValueError, match="Unknown strategy"):
        cfg.get_strategy("medium")  # type: ignore[arg-type]


def test_profiles_are_initially_identical():
    """Day-one requirement: long and short profiles start as identical clones."""
    cfg = load_config(REPO_ROOT / "config.yaml")
    long_strat = cfg.get_strategy("long")
    short_strat = cfg.get_strategy("short")
    assert long_strat.weights.model_dump() == short_strat.weights.model_dump()
    assert long_strat.thresholds.model_dump() == short_strat.thresholds.model_dump()
    assert long_strat.regime.model_dump() == short_strat.regime.model_dump()

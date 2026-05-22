"""Tests for config loading and validation (implements spec §2.2 weight constraint)."""
from pathlib import Path

import pytest

from backend.app.config import AppConfig, Weights, load_config


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

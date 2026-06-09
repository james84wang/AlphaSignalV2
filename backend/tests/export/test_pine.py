"""Tests for the TradingView Pine Script export (generator + endpoint)."""
from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.config import load_config
from backend.app.export.pine import generate_pine


def _norm(s: str) -> str:
    """Collapse runs of spaces so cosmetic input-alignment doesn't break asserts."""
    return re.sub(r" +", " ", s)


@pytest.fixture(scope="module")
def strat():
    return load_config().get_strategy("hidden_div")


# ── Generator ───────────────────────────────────────────────────────────────────

def test_pine_has_valid_v6_skeleton(strat):
    pine = generate_pine(strat)
    assert pine.startswith("//@version=6")
    assert 'indicator("' in pine
    # Built-ins that must back the ported logic.
    for fn in ("ta.ema(", "ta.macd(", "ta.rsi(", "ta.pivotlow(", "ta.pivothigh(", "ta.barssince("):
        assert fn in pine, f"missing {fn}"


def test_pine_bakes_default_config_values(strat):
    pine = _norm(generate_pine(strat))
    # Every input default comes straight from config.yaml.
    assert 'input.int(50, "EMA fast' in pine
    assert 'input.int(200, "EMA slow' in pine
    assert 'input.float(65, "Buy threshold' in pine
    assert 'input.float(35, "Sell threshold' in pine
    assert 'input.float(40, "TD13 sell weight' in pine
    assert 'input.int(10, "Entry confluence window' in pine


def test_pine_reflects_tuned_weights(strat):
    """Changing a weight/threshold changes the exported input default (config-driven)."""
    tuned = strat.model_copy(deep=True)
    tuned.entry.threshold = 80.0
    tuned.entry.weights.macd_hidden_bull = 42.0
    pine = _norm(generate_pine(tuned))
    assert 'input.float(80, "Buy threshold' in pine
    assert 'input.float(42, "MACD hidden-bull weight' in pine
    # The default 65 threshold must be gone (only the tuned value is emitted).
    assert 'input.float(65, "Buy threshold' not in pine


def test_pine_ports_demark_and_cooldown(strat):
    pine = generate_pine(strat)
    # DeMark state machine + opposite-setup cancellation present.
    assert "buyCdActive" in pine and "sellCdActive" in pine
    assert "td13Sell" in pine and "td9Buy" in pine
    # Cooldown that blocks repeat buys.
    assert "cooldown" in pine
    # Once-per-bar-close alerts (the logic doc's critical rule).
    assert "alert.freq_once_per_bar_close" in pine


# ── Endpoint ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from backend.app.api.config_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_pine_endpoint_downloads(client):
    r = client.get("/api/config/hidden_div/pine")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ".pine" in r.headers.get("content-disposition", "")
    assert r.text.startswith("//@version=6")


def test_pine_endpoint_rejects_unknown_strategy(client):
    r = client.get("/api/config/bogus/pine")
    assert r.status_code == 422

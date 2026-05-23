"""Tests for GET /api/market/overview."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.market import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _mock_overview(force_refresh: bool = False) -> dict:
    return {
        "indices": {
            "sp500": {"label": "S&P 500", "symbol": "^GSPC", "status": "ok", "last": 5000.0, "prev_close": 4980.0, "change_pct": 0.40},
            "vix": {"label": "VIX", "symbol": "^VIX", "status": "ok", "last": 15.5, "prev_close": 16.0, "change_pct": -3.12},
        },
        "fear_and_greed": {"label": "CNN Fear & Greed Index", "source": "...", "status": "ok", "score": 62.0, "label2": "Greed"},
        "cache_ttl_seconds": 900,
        "note": "test note",
    }


def test_overview_returns_200(client):
    with patch("backend.app.api.market.get_market_overview", side_effect=_mock_overview):
        r = client.get("/api/market/overview")
    assert r.status_code == 200
    data = r.json()
    assert "indices" in data
    assert "fear_and_greed" in data


def test_overview_contains_expected_keys(client):
    with patch("backend.app.api.market.get_market_overview", side_effect=_mock_overview):
        r = client.get("/api/market/overview")
    data = r.json()
    assert "sp500" in data["indices"]
    assert "vix" in data["indices"]
    assert data["indices"]["sp500"]["status"] == "ok"
    assert data["indices"]["sp500"]["last"] == 5000.0


def test_overview_handles_unavailable_gracefully(client):
    """A tile returning unavailable must not cause a 500."""
    def mock_unavailable(force_refresh: bool = False) -> dict:
        return {
            "indices": {
                "sp500": {"label": "S&P 500", "symbol": "^GSPC", "status": "unavailable"},
            },
            "fear_and_greed": {"label": "CNN Fear & Greed Index", "source": "...", "status": "unavailable"},
            "cache_ttl_seconds": 900,
            "note": "",
        }

    with patch("backend.app.api.market.get_market_overview", side_effect=mock_unavailable):
        r = client.get("/api/market/overview")
    assert r.status_code == 200
    assert r.json()["indices"]["sp500"]["status"] == "unavailable"
    assert r.json()["fear_and_greed"]["status"] == "unavailable"


def test_overview_refresh_param(client):
    """?refresh=true should pass force_refresh=True to the service."""
    calls: list[bool] = []

    def capturing_mock(force_refresh: bool = False) -> dict:
        calls.append(force_refresh)
        return _mock_overview()

    with patch("backend.app.api.market.get_market_overview", side_effect=capturing_mock):
        client.get("/api/market/overview?refresh=true")
    assert calls == [True]

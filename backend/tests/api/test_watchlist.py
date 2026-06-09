"""Tests for the multi-list watchlist API."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """TestClient for the watchlist router, backed by a temp DB."""
    from backend.app.db.models import make_session_factory

    factory = make_session_factory(tmp_path / "wl.db")
    monkeypatch.setattr("backend.app.api.watchlist.make_session_factory", lambda *a, **k: factory)

    from backend.app.api.watchlist import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_list_all_lists_empty(client):
    r = client.get("/api/watchlists")
    assert r.status_code == 200
    lists = r.json()["lists"]
    names = [l["name"] for l in lists]
    assert "Watchlist" in names
    assert "Watchlist - ChinaTech" in names
    assert all(l["count"] == 0 for l in lists)


def test_add_and_list(client):
    r = client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "AAPL"})
    assert r.status_code == 201
    assert r.json()["symbol"] == "AAPL"

    r2 = client.get("/api/watchlists")
    wl = next(l for l in r2.json()["lists"] if l["name"] == "Watchlist")
    assert [s["symbol"] for s in wl["symbols"]] == ["AAPL"]


def test_add_normalises_case(client):
    r = client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "msft"})
    assert r.status_code == 201
    assert r.json()["symbol"] == "MSFT"


def test_same_symbol_in_two_lists_allowed(client):
    assert client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "AAPL"}).status_code == 201
    assert client.post("/api/watchlists/Watchlist - 2/symbols", json={"symbol": "AAPL"}).status_code == 201


def test_duplicate_in_same_list_409(client):
    client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "AAPL"})
    r = client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "AAPL"})
    assert r.status_code == 409


def test_invalid_symbol_422(client):
    r = client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "123!!!"})
    assert r.status_code == 422


def test_unknown_list_404(client):
    r = client.post("/api/watchlists/Nonexistent/symbols", json={"symbol": "AAPL"})
    assert r.status_code == 404


def test_delete(client):
    client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "AAPL"})
    r = client.delete("/api/watchlists/Watchlist/symbols/AAPL")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    wl = next(l for l in client.get("/api/watchlists").json()["lists"] if l["name"] == "Watchlist")
    assert wl["count"] == 0


def test_delete_nonexistent_404(client):
    r = client.delete("/api/watchlists/Watchlist/symbols/ZZZZ")
    assert r.status_code == 404


def test_legacy_default_endpoint(client):
    client.post("/api/watchlists/Watchlist/symbols", json={"symbol": "NVDA"})
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["symbols"][0]["symbol"] == "NVDA"

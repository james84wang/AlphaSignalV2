"""Tests for GET/POST/DELETE /api/watchlist."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    """Return a TestClient with the watchlist DB pointed at a temp directory."""
    db_path = tmp_path / "test.db"
    # Patch the DB path used by watchlist.py
    with patch("backend.app.api.watchlist._DB_PATH", db_path):
        from backend.app.api.watchlist import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


def test_list_empty(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["symbols"] == []


def test_add_symbol(client):
    r = client.post("/api/watchlist", json={"symbol": "AAPL"})
    assert r.status_code == 201
    data = r.json()
    assert data["symbol"] == "AAPL"
    assert "added_at" in data


def test_add_symbol_normalises_case(client):
    r = client.post("/api/watchlist", json={"symbol": "msft"})
    assert r.status_code == 201
    assert r.json()["symbol"] == "MSFT"


def test_add_duplicate_returns_409(client):
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    r = client.post("/api/watchlist", json={"symbol": "AAPL"})
    assert r.status_code == 409


def test_add_invalid_symbol_returns_422(client):
    r = client.post("/api/watchlist", json={"symbol": "123INVALID!!!"})
    assert r.status_code == 422


def test_add_and_list(client):
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    client.post("/api/watchlist", json={"symbol": "MSFT"})
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    syms = [s["symbol"] for s in r.json()["symbols"]]
    assert "AAPL" in syms
    assert "MSFT" in syms
    assert r.json()["count"] == 2


def test_delete_symbol(client):
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    r = client.delete("/api/watchlist/AAPL")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/api/watchlist")
    assert r2.json()["count"] == 0


def test_delete_nonexistent_returns_404(client):
    r = client.delete("/api/watchlist/ZZZZ")
    assert r.status_code == 404


def test_add_with_note(client):
    r = client.post("/api/watchlist", json={"symbol": "NVDA", "note": "GPU play"})
    assert r.status_code == 201
    assert r.json()["note"] == "GPU play"

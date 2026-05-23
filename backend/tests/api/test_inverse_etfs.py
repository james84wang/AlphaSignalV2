"""Tests for GET /api/inverse-etfs and the inverse_etfs loader."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.data.inverse_etfs import get_inverse_etf, load_inverse_etf_map


# ── Loader unit tests ──────────────────────────────────────────────────────────

def test_load_from_csv(tmp_path: Path):
    csv = tmp_path / "inverse_etfs.csv"
    csv.write_text("underlying_symbol,inverse_etf_symbol,leverage,note\nSPY,SH,-1,Test\n")
    mapping = load_inverse_etf_map(csv)
    assert "SPY" in mapping
    assert mapping["SPY"]["inverse_etf_symbol"] == "SH"
    assert mapping["SPY"]["leverage"] == -1


def test_load_missing_file_returns_empty(tmp_path: Path):
    mapping = load_inverse_etf_map(tmp_path / "missing.csv")
    assert mapping == {}


def test_load_missing_columns_returns_empty(tmp_path: Path):
    csv = tmp_path / "bad.csv"
    csv.write_text("symbol,etf\nSPY,SH\n")
    mapping = load_inverse_etf_map(csv)
    assert mapping == {}


def test_get_inverse_etf_found(tmp_path: Path):
    csv = tmp_path / "inverse_etfs.csv"
    csv.write_text("underlying_symbol,inverse_etf_symbol,leverage,note\nQQQ,PSQ,-1,Test\n")
    result = get_inverse_etf("QQQ", path=csv)
    assert result == "PSQ"


def test_get_inverse_etf_not_found(tmp_path: Path):
    csv = tmp_path / "inverse_etfs.csv"
    csv.write_text("underlying_symbol,inverse_etf_symbol,leverage,note\nSPY,SH,-1,Test\n")
    result = get_inverse_etf("AAPL", path=csv)
    assert result is None


# ── API endpoint test ──────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path: Path):
    csv = tmp_path / "inverse_etfs.csv"
    csv.write_text(
        "underlying_symbol,inverse_etf_symbol,leverage,note\n"
        "SPY,SH,-1,ProShares Short S&P500\n"
        "QQQ,PSQ,-1,ProShares Short QQQ\n"
    )
    with patch("backend.app.data.inverse_etfs._INVERSE_ETFS_PATH", csv):
        from backend.app.api.inverse_etfs_routes import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


def test_get_inverse_etfs_endpoint(client):
    r = client.get("/api/inverse-etfs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert "SPY" in data["map"]
    assert data["map"]["SPY"]["inverse_etf_symbol"] == "SH"
    assert "QQQ" in data["map"]

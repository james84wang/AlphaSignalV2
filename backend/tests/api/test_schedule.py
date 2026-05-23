"""Tests for GET/PUT /api/schedule."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.schedule import router


@pytest.fixture()
def client(tmp_path: Path):
    settings_path = tmp_path / "schedule_settings.json"
    with (
        patch("backend.app.scheduler._SETTINGS_PATH", settings_path),
        patch("backend.app.scheduler._scheduler", None),
    ):
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


def test_get_schedule_defaults(client):
    r = client.get("/api/schedule")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is False
    assert data["time"] == "08:00"
    assert data["tz"] == "America/New_York"
    assert "next_run" in data
    assert "note" in data


def test_put_schedule_enable(client, tmp_path: Path):
    settings_path = tmp_path / "schedule_settings.json"
    with patch("backend.app.scheduler._SETTINGS_PATH", settings_path):
        r = client.put("/api/schedule", json={"enabled": True})
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True


def test_put_schedule_disable(client, tmp_path: Path):
    settings_path = tmp_path / "schedule_settings.json"
    with patch("backend.app.scheduler._SETTINGS_PATH", settings_path):
        # Enable first
        client.put("/api/schedule", json={"enabled": True})
        # Then disable
        r = client.put("/api/schedule", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_schedule_persists_across_reads(tmp_path: Path):
    """Setting enabled=True must survive a fresh load_settings() call."""
    from backend.app.scheduler import load_settings, save_settings

    settings_path = tmp_path / "schedule_settings.json"
    with patch("backend.app.scheduler._SETTINGS_PATH", settings_path):
        s = load_settings()
        s["enabled"] = True
        save_settings(s)
        reloaded = load_settings()
    assert reloaded["enabled"] is True


def test_catchup_not_triggered_when_disabled(tmp_path: Path):
    """_should_catchup returns False when enabled=False."""
    from backend.app.scheduler import _should_catchup

    settings = {"enabled": False, "catchup_enabled": True, "last_run_date": "2020-01-01"}
    assert _should_catchup(settings) is False


def test_catchup_not_triggered_when_already_ran_today(tmp_path: Path):
    """_should_catchup returns False when last_run_date == today."""
    from datetime import date

    from backend.app.scheduler import _should_catchup

    settings = {"enabled": True, "catchup_enabled": True, "last_run_date": str(date.today())}
    assert _should_catchup(settings) is False

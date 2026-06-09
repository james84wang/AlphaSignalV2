"""Tests for the optimiser API (start → poll → result, promote, report).

Uses synthetic OHLCV via a fake cache and routes all file output (candidate
config, report, trials CSV, Optuna study db) into a temp dir, so a test run
never touches the repo's real config.yaml or data/ files.
"""
from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _mk(n: int = 320, seed: int = 1, base: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = np.maximum(base + np.cumsum(rng.standard_normal(n) * 0.8), 1.0)
    o = c + rng.uniform(-0.5, 0.5, n)
    h = np.maximum(o, c) + rng.uniform(0.1, 1.0, n)
    lo = np.minimum(o, c) - rng.uniform(0.1, 1.0, n)
    idx = pd.date_range("2021-06-10", periods=n, freq="B")
    return pd.DataFrame(
        {"open": o, "high": h, "low": lo, "close": c, "volume": rng.integers(5e5, 5e6, n)},
        index=idx,
    )


_DATA = {s: _mk(seed=i * 7) for i, s in enumerate(["AAPL", "MSFT", "NVDA", "BABA", "JD"])}


class _FakeCache:
    def __init__(self, *a, **k):
        pass

    def get_daily_bars(self, sym: str, s: date, e: date) -> pd.DataFrame:
        df = _DATA.get(sym)
        if df is None:
            raise ValueError(f"no data for {sym}")
        return df.loc[(df.index >= pd.Timestamp(s)) & (df.index <= pd.Timestamp(e))]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import backend.app.api.optimizer as opt

    # Synthetic data + a fixed 5-symbol universe.
    monkeypatch.setattr(opt, "ParquetCache", lambda *a, **k: _FakeCache())
    monkeypatch.setattr(opt, "resolve_universe", lambda u, cfg: ["AAPL", "MSFT", "NVDA", "BABA", "JD"])

    # Route the Optuna study db into tmp so test runs don't reuse/share state.
    monkeypatch.setattr("backend.app.optimizer.core._DATA_DIR", tmp_path)

    # Redirect file outputs into tmp; the candidate is a copy of the real config
    # so the promote endpoint can validate it.
    real_cfg_text = (opt._REPO_ROOT / "config.yaml").read_text()
    cand = tmp_path / "config.candidate.hidden_div.yaml"
    rep = tmp_path / "report.md"
    csvp = tmp_path / "trials.csv"

    def _save_candidate(result, strategy, cfg, output_path=None):
        cand.write_text(real_cfg_text)
        return cand

    def _gen_report(*a, **k):
        rep.write_text("# Optimisation Report\n\n## Verdict\n")
        return rep

    def _write_csv(*a, **k):
        csvp.write_text("trial,score\n0,0.1\n")
        return csvp

    monkeypatch.setattr(opt, "save_candidate_config", _save_candidate)
    monkeypatch.setattr(opt, "generate_report", _gen_report)
    monkeypatch.setattr(opt, "write_trials_csv", _write_csv)

    # Live config writes (promote) go to a temp file, never the repo config.
    live = tmp_path / "live_config.yaml"
    live.write_text(real_cfg_text)
    monkeypatch.setattr(opt, "_CONFIG_PATH", live)

    app = FastAPI()
    app.include_router(opt.router)
    return TestClient(app), live


def _run_to_done(tc: TestClient, body: dict, timeout_s: float = 90.0):
    r = tc.post("/api/optimize", json=body)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = tc.get(f"/api/optimize/{jid}").json()
        if s["status"] in ("done", "error"):
            return jid, s
        time.sleep(0.3)
    raise AssertionError("optimisation did not finish within timeout")


# ── Validation ────────────────────────────────────────────────────────────────

def test_unknown_universe_422(client):
    tc, _ = client
    assert tc.post("/api/optimize", json={"universe": "bogus"}).status_code == 422


def test_bad_folds_and_trials_422(client):
    tc, _ = client
    assert tc.post("/api/optimize", json={"universe": "watchlist", "folds": 1}).status_code == 422
    assert tc.post("/api/optimize", json={"universe": "watchlist", "trials": 0}).status_code == 422


def test_unknown_job_404(client):
    tc, _ = client
    assert tc.get("/api/optimize/deadbeef").status_code == 404


# ── Full run ──────────────────────────────────────────────────────────────────

def test_full_run_result_shape(client):
    tc, _ = client
    jid, s = _run_to_done(tc, {"universe": "watchlist", "trials": 10, "folds": 2, "seed": 42})
    assert s["status"] == "done", s.get("error")
    assert isinstance(s["pass_verdict"], bool)
    assert s["verdict_tier"] in ("ROBUST", "SUSPECT", "OVERFIT")
    for k in ("insample_metrics", "holdout_metrics", "wf_metrics"):
        assert isinstance(s[k], dict)
    assert "entry" in s["best_strat"] and "exit" in s["best_strat"]
    assert s["n_trials"] >= 1
    # report endpoint serves the markdown
    rep = tc.get(f"/api/optimize/{jid}/report")
    assert rep.status_code == 200
    assert rep.text.startswith("# Optimisation Report")


# ── Promote ───────────────────────────────────────────────────────────────────

def test_promote_writes_temp_config_not_repo(client):
    tc, live = client
    before = live.read_text()
    jid, s = _run_to_done(tc, {"universe": "watchlist", "trials": 8, "folds": 2, "seed": 7})
    assert s["status"] == "done", s.get("error")

    r = tc.post(f"/api/optimize/{jid}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # The (temp) live config is now valid YAML with the hidden_div strategy.
    promoted = yaml.safe_load(live.read_text())
    assert "hidden_div" in promoted["strategies"]
    # before was also valid; promotion produced a parseable config
    assert yaml.safe_load(before)["strategies"]


def test_promote_unknown_job_404(client):
    tc, _ = client
    assert tc.post("/api/optimize/deadbeef/promote").status_code == 404

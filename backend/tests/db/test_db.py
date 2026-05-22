"""Tests for backend.app.db: table creation, insert, and query round-trip."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from backend.app.db.models import Run, Signal, config_hash, init_db, make_session_factory


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path):
    """Return a path to a fresh temporary SQLite database."""
    return tmp_path / "test_signals.db"


# ── init_db ────────────────────────────────────────────────────────────────────

def test_init_db_creates_tables(tmp_db: Path) -> None:
    engine = init_db(tmp_db)
    insp = inspect(engine)
    tables = insp.get_table_names()
    assert "runs" in tables, "Expected 'runs' table"
    assert "signals" in tables, "Expected 'signals' table"


def test_init_db_idempotent(tmp_db: Path) -> None:
    """Calling init_db twice must not raise."""
    init_db(tmp_db)
    init_db(tmp_db)  # second call should be a no-op


# ── Insert / query round-trip ──────────────────────────────────────────────────

def test_insert_run_and_signal(tmp_db: Path) -> None:
    """Writing a Run + Signal and reading them back gives identical values."""
    SessionFactory = make_session_factory(tmp_db)

    sub = {"candlestick": 90.0, "p3": 70.0, "p5": 85.0, "volume": 60.0,
           "ema": 30.0, "sr": 20.0, "macd": 35.0, "rsi": 40.0}

    with SessionFactory() as session:
        run = Run(
            run_timestamp=datetime.utcnow().isoformat(timespec="seconds"),
            universe="watchlist",
            config_hash="abc123def456abcd",
            n_symbols=5,
            n_success=4,
            n_errors=1,
            duration_seconds=2.35,
        )
        session.add(run)
        session.flush()

        sig = Signal(
            run_id=run.id,
            date="2025-01-15",
            symbol="AAPL",
            composite=72.5,
            signal="Buy",
            long_allowed=True,
            short_allowed=False,
            sub_scores_json=json.dumps(sub),
        )
        session.add(sig)
        session.commit()
        run_id = run.id

    # Fresh session — verify round-trip.
    with SessionFactory() as session:
        runs = session.execute(select(Run)).scalars().all()
        assert len(runs) == 1
        r = runs[0]
        assert r.id == run_id
        assert r.universe == "watchlist"
        assert r.n_symbols == 5
        assert r.n_success == 4
        assert r.n_errors == 1
        assert abs(r.duration_seconds - 2.35) < 1e-6

        sigs = session.execute(
            select(Signal).where(Signal.run_id == run_id)
        ).scalars().all()
        assert len(sigs) == 1
        s = sigs[0]
        assert s.symbol == "AAPL"
        assert s.date == "2025-01-15"
        assert abs(s.composite - 72.5) < 1e-6
        assert s.signal == "Buy"
        assert s.long_allowed is True
        assert s.short_allowed is False
        recovered = json.loads(s.sub_scores_json)
        assert recovered["candlestick"] == 90.0
        assert recovered["rsi"] == 40.0


def test_multiple_signals_ordering(tmp_db: Path) -> None:
    """Multiple signals can be stored and retrieved ordered by composite desc."""
    SessionFactory = make_session_factory(tmp_db)
    rows = [
        ("AAPL", 72.5, "Buy"),
        ("MSFT", -71.0, "Sell"),
        ("NVDA", 12.0, "Hold"),
    ]

    with SessionFactory() as session:
        run = Run(
            run_timestamp=datetime.utcnow().isoformat(),
            universe="watchlist",
            config_hash="deadbeef12345678",
            n_symbols=3, n_success=3, n_errors=0, duration_seconds=1.0,
        )
        session.add(run)
        session.flush()
        for sym, comp, sig in rows:
            session.add(Signal(
                run_id=run.id,
                date="2025-06-01",
                symbol=sym,
                composite=comp,
                signal=sig,
                long_allowed=True,
                short_allowed=False,
                sub_scores_json=json.dumps({}),
            ))
        session.commit()
        run_id = run.id

    with SessionFactory() as session:
        sigs = session.execute(
            select(Signal)
            .where(Signal.run_id == run_id)
            .order_by(Signal.composite.desc())
        ).scalars().all()
        assert [s.symbol for s in sigs] == ["AAPL", "NVDA", "MSFT"]


# ── config_hash ────────────────────────────────────────────────────────────────

def test_config_hash_is_deterministic(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("weights:\n  rsi: 10\n")
    h1 = config_hash(cfg)
    h2 = config_hash(cfg)
    assert h1 == h2
    assert len(h1) == 16


def test_config_hash_changes_with_content(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("weights:\n  rsi: 10\n")
    h1 = config_hash(cfg)
    cfg.write_text("weights:\n  rsi: 20\n")
    h2 = config_hash(cfg)
    assert h1 != h2

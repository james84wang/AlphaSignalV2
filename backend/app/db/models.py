"""SQLAlchemy models and helpers for the AlphaSignal signals database.

Tables
------
runs         — one row per run_daily.py invocation (metadata + stats)
signals      — one row per (run_id, date, symbol) with full audit data
watchlist    — user's symbol watchlist (managed via API)

The database file lives alongside the Parquet cache at:
    <repo-root>/../data/signals.db
(i.e. the same ``Claude/Code/data/`` directory used by the Parquet cache)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

# Match the existing parents[4] convention so signals.db lands in the
# same ``Claude/Code/data/`` directory as the Parquet bar cache.
_DATA_DIR = Path(__file__).resolve().parents[4] / "data"
_DEFAULT_DB_PATH = _DATA_DIR / "signals.db"


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One row per run_daily.py invocation."""

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_timestamp = Column(String, nullable=False)   # ISO 8601 UTC datetime
    universe = Column(String, nullable=False)        # "watchlist" | "sp500" | "combined"
    strategy = Column(String, nullable=False, server_default="long")  # "long" | "short"
    config_hash = Column(String, nullable=False)     # first 16 hex chars of SHA-256(config.yaml)
    n_symbols = Column(Integer, nullable=False)      # total symbols attempted
    n_success = Column(Integer, nullable=False)      # signals written
    n_errors = Column(Integer, nullable=False)       # symbols skipped due to missing/bad data
    duration_seconds = Column(Float, nullable=False)

    signals = relationship("Signal", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (
            f"<Run id={self.id} ts={self.run_timestamp!r} "
            f"universe={self.universe!r} strategy={self.strategy!r} "
            f"hash={self.config_hash!r} ok={self.n_success}/{self.n_symbols}>"
        )


class Signal(Base):
    """One row per (run_id, date, symbol).

    sub_scores_json is a JSON object mapping component name → sub-score (float).
    inverse_etf is populated for short-strategy signals where a mapping exists.
    """

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    date = Column(String, nullable=False)            # ISO date, e.g. "2024-01-15"
    symbol = Column(String, nullable=False)
    strategy = Column(String, nullable=False, server_default="long")  # "long" | "short"
    composite = Column(Float, nullable=False)        # weighted composite in [-100, +100]
    signal = Column(String, nullable=False)          # "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell"
    long_allowed = Column(Boolean, nullable=False)   # regime gate: longs permitted?
    short_allowed = Column(Boolean, nullable=False)  # regime gate: shorts permitted?
    sub_scores_json = Column(String, nullable=False) # JSON: {component: sub_score, ...}
    inverse_etf = Column(String, nullable=True)      # mapped inverse ETF symbol (short runs only); null if unmapped

    run = relationship("Run", back_populates="signals")

    def __repr__(self) -> str:
        return (
            f"<Signal {self.symbol} {self.date} strategy={self.strategy!r} "
            f"{self.signal!r} composite={self.composite:.2f}>"
        )


class WatchlistEntry(Base):
    """User-managed watchlist stored in SQLite.

    Seeded from data/watchlist.csv on first startup; managed via the API thereafter.
    """

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, unique=True)
    added_at = Column(String, nullable=False)  # ISO 8601 UTC datetime
    note = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<WatchlistEntry {self.symbol!r} added={self.added_at!r}>"


# ── Engine / session helpers ───────────────────────────────────────────────────

def get_engine(db_path: Path | str | None = None):
    """Return a SQLAlchemy engine for the given SQLite path (or the default)."""
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def init_db(db_path: Path | str | None = None):
    """Create all tables if they don't exist. Returns the engine."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def migrate_db(engine) -> None:
    """Apply any pending schema migrations (idempotent).

    SQLite's create_all never adds columns to existing tables, so new
    columns must be added here with ALTER TABLE … ADD COLUMN.
    """
    insp = inspect(engine)

    # Migrations for the signals table.
    if "signals" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("signals")}
        with engine.connect() as conn:
            if "strategy" not in existing:
                conn.execute(text("ALTER TABLE signals ADD COLUMN strategy TEXT NOT NULL DEFAULT 'long'"))
            if "inverse_etf" not in existing:
                conn.execute(text("ALTER TABLE signals ADD COLUMN inverse_etf TEXT"))
            conn.commit()

    # Migrations for the runs table.
    if "runs" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("runs")}
        with engine.connect() as conn:
            if "strategy" not in existing:
                conn.execute(text("ALTER TABLE runs ADD COLUMN strategy TEXT NOT NULL DEFAULT 'long'"))
            conn.commit()


def make_session_factory(db_path: Path | str | None = None):
    """Init DB and return a sessionmaker bound to that engine."""
    engine = init_db(db_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ── Config hash ────────────────────────────────────────────────────────────────

def config_hash(config_path: Path) -> str:
    """Return first 16 hex chars of SHA-256(config.yaml) for reproducibility."""
    return hashlib.sha256(config_path.read_bytes()).hexdigest()[:16]

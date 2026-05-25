"""SQLAlchemy models for backtest run persistence.

Tables:
  backtest_runs   — one row per run_backtest() call (params + metrics)
  backtest_trades — one row per closed trade
  backtest_equity — daily equity curve points

The database file is the same signals.db used by Phase 3.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Column, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from backend.app.db.models import Base, get_engine, init_db, make_session_factory

if TYPE_CHECKING:
    from backend.app.backtest.engine import BacktestResult


class BacktestRun(Base):
    """One row per backtest execution."""

    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_timestamp = Column(String, nullable=False)   # ISO 8601 UTC
    config_hash = Column(String, nullable=False)     # first 16 hex of SHA-256(config.yaml)
    strategy = Column(String, nullable=False, default="long")   # "long" | "short"
    params_json = Column(String, nullable=False)     # serialised BacktestResult.params
    metrics_json = Column(String, nullable=False)    # serialised BacktestResult.metrics
    duration_seconds = Column(Float, nullable=False)
    survivorship_note = Column(String, nullable=False)
    coverage_json = Column(String, nullable=True)    # JSON CoverageReport (short runs only)

    trades = relationship("BacktestTrade", back_populates="run", cascade="all, delete-orphan")
    equity = relationship("BacktestEquity", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        m = json.loads(self.metrics_json)
        return (
            f"<BacktestRun id={self.id} ts={self.run_timestamp!r} "
            f"sharpe={m.get('sharpe')} maxDD={m.get('max_drawdown_pct')}%>"
        )


class BacktestTrade(Base):
    """One row per closed trade."""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)          # "long" | "short"
    entry_date = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_date = Column(String, nullable=False)
    exit_price = Column(Float, nullable=False)
    shares = Column(Float, nullable=False)
    initial_stop = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    pnl_pct = Column(Float, nullable=False)
    exit_reason = Column(String, nullable=False)   # "stop" | "signal" | "end_of_data"
    # Short-only fields (null for long trades)
    underlying_symbol = Column(String, nullable=True)   # underlying that generated signal
    trade_instrument = Column(String, nullable=True)    # the actual ETF traded
    synthetic_pnl = Column(Float, nullable=True)        # decay diagnostic: −1× underlying return
    synthetic_pnl_pct = Column(Float, nullable=True)

    run = relationship("BacktestRun", back_populates="trades")


class BacktestEquity(Base):
    """One row per trading day per backtest run (equity curve)."""

    __tablename__ = "backtest_equity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=False)
    date = Column(String, nullable=False)
    equity = Column(Float, nullable=False)
    n_open = Column(Integer, nullable=False)

    run = relationship("BacktestRun", back_populates="equity")


def init_backtest_db(db_path: Path | str | None = None):
    """Create backtest tables if they don't exist, and migrate any missing columns.

    SQLAlchemy's create_all() only creates tables; it never alters existing ones.
    This function additionally runs lightweight ALTER TABLE migrations so that
    columns added to the model after the DB was first created are always present.
    """
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)

    # ── Idempotent column migrations ──────────────────────────────────────────
    # Maps table → list of (column_name, DDL_type_and_default) to add if absent.
    _MIGRATIONS: dict[str, list[tuple[str, str]]] = {
        "backtest_runs": [
            ("strategy",      "VARCHAR NOT NULL DEFAULT 'long'"),
            ("coverage_json", "VARCHAR"),
        ],
        "backtest_trades": [
            ("underlying_symbol", "VARCHAR"),
            ("trade_instrument",  "VARCHAR"),
            ("synthetic_pnl",     "FLOAT"),
            ("synthetic_pnl_pct", "FLOAT"),
        ],
    }
    with engine.connect() as conn:
        from sqlalchemy import text
        for table, cols in _MIGRATIONS.items():
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            existing_cols = {row[1] for row in result.fetchall()}
            for col_name, col_def in cols:
                if col_name not in existing_cols:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    )
        conn.commit()

    return engine


def save_backtest_result(
    result: "BacktestResult",
    config_hash: str,
    duration_seconds: float,
    db_path: Path | str | None = None,
) -> int:
    """Persist a BacktestResult to SQLite. Returns the new run id."""
    Session = make_session_factory(db_path)

    # Ensure backtest tables exist
    init_backtest_db(db_path)

    coverage_json = None
    if result.coverage_report is not None:
        coverage_json = json.dumps(result.coverage_report.to_dict(), default=str)

    with Session() as session:
        run = BacktestRun(
            run_timestamp=datetime.now(tz=timezone.utc).isoformat(),
            config_hash=config_hash,
            strategy=getattr(result, "strategy", "long"),
            params_json=json.dumps(result.params, default=str),
            metrics_json=json.dumps(result.metrics, default=str),
            duration_seconds=round(duration_seconds, 2),
            survivorship_note=result.survivorship_note,
            coverage_json=coverage_json,
        )
        session.add(run)
        session.flush()  # get run.id

        for t in result.trades:
            session.add(BacktestTrade(
                run_id=run.id,
                symbol=t.symbol,
                side=t.side,
                entry_date=t.entry_date,
                entry_price=t.entry_price,
                exit_date=t.exit_date,
                exit_price=t.exit_price,
                shares=t.shares,
                initial_stop=t.initial_stop,
                pnl=t.pnl,
                pnl_pct=t.pnl_pct,
                exit_reason=t.exit_reason,
                underlying_symbol=getattr(t, "underlying_symbol", None),
                trade_instrument=getattr(t, "trade_instrument", None),
                synthetic_pnl=getattr(t, "synthetic_pnl", None),
                synthetic_pnl_pct=getattr(t, "synthetic_pnl_pct", None),
            ))

        for e in result.equity_curve:
            session.add(BacktestEquity(
                run_id=run.id,
                date=e["date"],
                equity=e["equity"],
                n_open=e.get("n_open", 0),
            ))

        session.commit()
        run_id = run.id

    return run_id

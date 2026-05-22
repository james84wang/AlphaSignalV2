#!/usr/bin/env python
"""AlphaSignal — Signal Inspector.

A helper script to browse stored signals from SQLite without writing SQL.

Usage (from repo root, AlphaSignalV2/):
-----------------------------------------
  # Show the most recent run's ranked signals:
  python scripts/query_signals.py

  # Show a specific run by ID:
  python scripts/query_signals.py --run 3

  # List all past runs:
  python scripts/query_signals.py --list-runs

  # Show sub-scores for a specific symbol in the latest run:
  python scripts/query_signals.py --symbol AAPL

  # Show the last N runs:
  python scripts/query_signals.py --list-runs --last 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select

from backend.app.db.models import Run, Signal, init_db, make_session_factory

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_PATH = _DATA_DIR / "signals.db"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inspect stored AlphaSignal results.")
    p.add_argument("--run", type=int, default=None, metavar="ID",
                   help="Show signals from run #ID. Default: latest run.")
    p.add_argument("--list-runs", action="store_true",
                   help="Print a summary table of all stored runs.")
    p.add_argument("--last", type=int, default=20, metavar="N",
                   help="With --list-runs, show the last N runs (default 20).")
    p.add_argument("--symbol", type=str, default=None, metavar="TICKER",
                   help="Show per-component sub-scores for this symbol.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if not _DB_PATH.exists():
        print(f"No database found at {_DB_PATH}")
        print("Run `python scripts/run_daily.py` first.")
        sys.exit(1)

    SessionFactory = make_session_factory(_DB_PATH)

    with SessionFactory() as session:
        # ── List all runs ─────────────────────────────────────────────────────
        if args.list_runs:
            runs = session.execute(
                select(Run).order_by(Run.id.desc()).limit(args.last)
            ).scalars().all()
            if not runs:
                print("No runs stored yet.")
                return
            print(f"\n{'='*72}")
            print(f"  Past Runs  (most recent first, showing up to {args.last})")
            print(f"{'='*72}")
            print(f"  {'ID':<6} {'Timestamp':<22} {'Universe':<12} {'OK/Total':<10} {'Secs':>6}  Config Hash")
            print(f"  {'─'*60}")
            for r in runs:
                print(
                    f"  {r.id:<6} {r.run_timestamp:<22} {r.universe:<12} "
                    f"{r.n_success}/{r.n_symbols:<8} {r.duration_seconds:>6.1f}  {r.config_hash}"
                )
            print(f"{'='*72}\n")
            return

        # ── Resolve run to inspect ─────────────────────────────────────────────
        if args.run is not None:
            run = session.get(Run, args.run)
            if run is None:
                print(f"Run #{args.run} not found.")
                sys.exit(1)
        else:
            run = session.execute(select(Run).order_by(Run.id.desc()).limit(1)).scalar_one_or_none()
            if run is None:
                print("No runs stored yet. Run `python scripts/run_daily.py` first.")
                sys.exit(1)

        signals = (
            session.execute(
                select(Signal)
                .where(Signal.run_id == run.id)
                .order_by(Signal.composite.desc())
            )
            .scalars()
            .all()
        )

        print(f"\n{'='*72}")
        print(f"  Run #{run.id}  |  {run.run_timestamp}  |  universe={run.universe}")
        print(f"  Config hash: {run.config_hash}  |  {run.n_success}/{run.n_symbols} OK  |  {run.duration_seconds:.1f}s")
        print(f"{'='*72}")

        # ── Symbol drill-down: show sub-scores ─────────────────────────────────
        if args.symbol:
            sym = args.symbol.upper()
            match = next((s for s in signals if s.symbol == sym), None)
            if match is None:
                print(f"\n  {sym} not found in run #{run.id}.\n")
                return
            sub = json.loads(match.sub_scores_json)
            print(f"\n  {sym}  {match.date}  →  {match.signal}  (composite {match.composite:+.2f})")
            print(f"  Regime: long_allowed={match.long_allowed}  short_allowed={match.short_allowed}")
            print(f"\n  {'Component':<14} {'Sub-score':>10}  (weight × sub = weighted)")
            print(f"  {'─'*44}")
            for name, score in sub.items():
                print(f"  {name:<14} {score:>10.2f}")
            print()
            return

        # ── Ranked table for the run ───────────────────────────────────────────
        print(f"  {'#':<4} {'Symbol':<8} {'Date':<12} {'Signal':<14} {'Composite':>10}  Regime")
        print(f"  {'─'*58}")
        for rank, s in enumerate(signals, 1):
            regime = ("L" if s.long_allowed else "-") + ("S" if s.short_allowed else "-")
            marker = " ▲" if s.signal in ("Strong Buy", "Buy") else (" ▼" if s.signal in ("Strong Sell", "Sell") else "")
            print(
                f"  {rank:<4} {s.symbol:<8} {s.date:<12} {s.signal:<14} "
                f"{s.composite:>+10.2f}  [{regime}]{marker}"
            )
        print(f"{'='*72}\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Run the scoring engine over cached AAPL history and print the latest bar's audit object.

Usage (from repo root):
    python scripts/run_engine.py [SYMBOL] [--days N]

Examples:
    python scripts/run_engine.py              # AAPL, 300 days
    python scripts/run_engine.py MSFT --days 500
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure the repo root is on sys.path so `backend.*` imports work
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.scoring.confluence import run_engine

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AlphaSignal engine on a symbol.")
    parser.add_argument("symbol", nargs="?", default="AAPL")
    parser.add_argument("--days", type=int, default=300, help="Days of history to fetch")
    args = parser.parse_args()

    symbol: str = args.symbol.upper()
    end = date.today()
    start = end - timedelta(days=args.days)

    cfg = load_config()
    cache = ParquetCache(YFinanceProvider())

    print(f"Fetching {symbol} {start} → {end}…", flush=True)
    df = cache.get_daily_bars(symbol, start, end)

    if df.empty:
        print(f"ERROR: No data returned for {symbol}.", file=sys.stderr)
        sys.exit(1)

    print(f"Running engine over {len(df)} bars…", flush=True)
    results = run_engine(df, cfg)

    if not results:
        print("ERROR: Engine returned no results.", file=sys.stderr)
        sys.exit(1)

    latest = results[-1]
    print(f"\n{'='*60}")
    print(f"LATEST BAR AUDIT — {symbol}  {latest['date']}")
    print(f"{'='*60}")
    print(f"  Composite : {latest['composite']:.4f}")
    print(f"  Signal    : {latest['signal']}")
    print(f"  Regime    : long_allowed={latest['regime']['long_allowed']}")
    print(f"  Entry score: {latest['entry_score']:.1f}   Exit score: {latest['exit_score']:.1f}")
    print(f"{'─'*60}")
    print(f"  {'Component':<20} {'Side':>6} {'Weight':>7} {'Fired':>6} {'Contrib':>9}")
    print(f"  {'─'*52}")
    for name, data in latest["components"].items():
        print(f"  {name:<20} {data['side']:>6} {data['weight']:>7.0f} "
              f"{str(data['fired']):>6} {data['contribution']:>9.2f}")
    print(f"{'='*60}")

    # Also dump the full JSON audit object for inspection
    print("\nFull JSON audit (latest bar):")
    print(json.dumps(latest, indent=2))


if __name__ == "__main__":
    main()

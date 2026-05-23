#!/usr/bin/env python
"""AlphaSignal — Daily Signal Runner.

Loads a universe/watchlist, ensures OHLCV data is cached/fresh, computes
signals for every symbol on the target date, persists results to SQLite,
and prints a ranked table (strongest Buy → strongest Sell).

Usage (run from the repo root, AlphaSignalV2/):
----------------------------------------------------
  # Today's signals for your watchlist (default, long profile):
  python scripts/run_daily.py

  # Run the short profile:
  python scripts/run_daily.py --strategy short

  # Use the full S&P 500:
  python scripts/run_daily.py --universe sp500

  # A specific historical date:
  python scripts/run_daily.py --date 2025-01-15

  # Watchlist + specific date, verbose:
  python scripts/run_daily.py --date 2025-01-15 --verbose

Outputs
-------
- Ranked signal table printed to stdout.
- Every run + all per-symbol signals persisted to SQLite at
  Claude/Code/data/signals.db  (same directory as the Parquet bar cache).

No look-ahead bias: signal for date T uses only bars up to and including T.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Repo-root path resolution ─────────────────────────────────────────────────
# scripts/run_daily.py is one level below the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.universe import Universe
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.db.models import Run, Signal, config_hash, make_session_factory
from backend.app.scoring.composite import run_engine

# ── Constants ──────────────────────────────────────────────────────────────────
_CONFIG_PATH = _REPO_ROOT / "config.yaml"
# Use the same parents[4] data dir as the Parquet cache (Claude/Code/data/).
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_PATH = _DATA_DIR / "signals.db"
_WATCHLIST_PATH = _REPO_ROOT / "data" / "watchlist.csv"

# Bars of history required for warm-up of EMA200 + safety buffer.
_HISTORY_DAYS = 400

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_daily")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AlphaSignal daily signals for a universe and persist to SQLite."
    )
    parser.add_argument(
        "--universe",
        choices=["watchlist", "sp500"],
        default="watchlist",
        help=(
            "Symbol universe to process. "
            "'watchlist' = data/watchlist.csv only (default). "
            "'sp500' = full S&P 500 list."
        ),
    )
    parser.add_argument(
        "--strategy",
        choices=["long", "short"],
        default="long",
        help="Strategy profile to score against: 'long' (default) or 'short'.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Target date. Defaults to today; falls back to latest available trading day.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show INFO-level progress logs.",
    )
    return parser.parse_args()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve_target_date(target_str: str | None) -> date:
    if target_str:
        try:
            return date.fromisoformat(target_str)
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got {target_str!r}", file=sys.stderr)
            sys.exit(1)
    return date.today()


def _get_symbols(universe: str) -> list[str]:
    """Return the symbol list for the chosen universe."""
    if universe == "watchlist":
        u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=False)
        syms = u.watchlist_symbols()
        if not syms:
            logger.warning("Watchlist empty or not found at %s", _WATCHLIST_PATH)
        return syms
    else:
        u = Universe(watchlist_path=_WATCHLIST_PATH, include_sp500=True)
        return u.symbols


def _signal_for_date(results: list[dict], target: date) -> dict | None:
    """Return the bar dict whose date == target, searching newest→oldest."""
    target_str = str(target)
    for bar in reversed(results):
        if bar["date"] == target_str:
            return bar
    return None


def _latest_bar(results: list[dict]) -> dict | None:
    """Return the last (newest) bar in results."""
    return results[-1] if results else None


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    target_date = _resolve_target_date(args.date)
    universe_name = args.universe
    strategy_name = args.strategy

    print(f"\n{'='*68}")
    print(f"  AlphaSignal — Daily Signal Runner")
    print(f"{'='*68}")
    print(f"  Universe  : {universe_name}")
    print(f"  Strategy  : {strategy_name}")
    print(f"  Target    : {target_date}")

    cfg = load_config(_CONFIG_PATH)
    cfg_hash = config_hash(_CONFIG_PATH)
    print(f"  Config    : {cfg_hash}  ({_CONFIG_PATH.name})")

    symbols = _get_symbols(universe_name)
    if not symbols:
        print(
            f"\nERROR: No symbols found.\n"
            f"  For 'watchlist': check {_WATCHLIST_PATH}\n"
            f"  Expected format: two columns — symbol,exchange",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  Symbols   : {len(symbols)}")
    print(f"{'─'*68}\n")

    provider = YFinanceProvider()
    cache = ParquetCache(provider)
    end_date = target_date
    start_date = target_date - timedelta(days=_HISTORY_DAYS)

    session_factory = make_session_factory(_DB_PATH)

    successes: list[dict] = []
    errors: list[str] = []

    t0 = time.monotonic()

    for i, symbol in enumerate(symbols, 1):
        label = f"[{i:>{len(str(len(symbols)))}}/{len(symbols)}] {symbol:<8}"
        print(f"  {label}", end=" ", flush=True)
        try:
            df = cache.get_daily_bars(symbol, start_date, end_date)
            if df.empty:
                print("SKIP  (no data returned)")
                errors.append(symbol)
                continue

            results = run_engine(df, cfg, strategy=strategy_name)
            if not results:
                print("SKIP  (engine: no results)")
                errors.append(symbol)
                continue

            # Prefer exact match for target_date; fall back to newest available.
            bar = _signal_for_date(results, target_date)
            fallback_note = ""
            if bar is None:
                bar = _latest_bar(results)
                if bar is None:
                    print("SKIP  (engine: no bars)")
                    errors.append(symbol)
                    continue
                fallback_note = f" [using {bar['date']}]"

            sub_scores = {
                name: round(comp["sub"], 4)
                for name, comp in bar["components"].items()
            }

            successes.append({
                "symbol": symbol,
                "date": bar["date"],
                "composite": bar["composite"],
                "signal": bar["signal"],
                "long_allowed": bar["regime"]["long_allowed"],
                "short_allowed": bar["regime"]["short_allowed"],
                "sub_scores": sub_scores,
            })

            sig_pad = f"{bar['signal']:<12}"
            comp_str = f"{bar['composite']:>+8.2f}"
            print(f"{sig_pad}  composite={comp_str}{fallback_note}")

        except Exception as exc:
            print(f"ERROR  {exc}")
            logger.exception("Unexpected error for %s", symbol)
            errors.append(symbol)

    duration = time.monotonic() - t0

    # ── Persist to SQLite ──────────────────────────────────────────────────────
    with session_factory() as session:
        run = Run(
            run_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            universe=universe_name,
            strategy=strategy_name,
            config_hash=cfg_hash,
            n_symbols=len(symbols),
            n_success=len(successes),
            n_errors=len(errors),
            duration_seconds=round(duration, 2),
        )
        session.add(run)
        session.flush()  # populate run.id

        for s in successes:
            session.add(Signal(
                run_id=run.id,
                date=s["date"],
                symbol=s["symbol"],
                strategy=strategy_name,
                composite=s["composite"],
                signal=s["signal"],
                long_allowed=s["long_allowed"],
                short_allowed=s["short_allowed"],
                sub_scores_json=json.dumps(s["sub_scores"]),
            ))

        session.commit()
        run_id = run.id

    # ── Ranked output table ────────────────────────────────────────────────────
    ranked = sorted(successes, key=lambda x: x["composite"], reverse=True)

    print(f"\n{'='*68}")
    date_used = ranked[0]["date"] if ranked else str(target_date)
    print(f"  RANKED SIGNAL TABLE  |  {date_used}  |  run #{run_id}")
    print(f"{'='*68}")
    print(f"  {'#':<4} {'Symbol':<8} {'Signal':<14} {'Composite':>10}  Regime")
    print(f"  {'─'*52}")

    for rank, s in enumerate(ranked, 1):
        regime = ("L" if s["long_allowed"] else "-") + ("S" if s["short_allowed"] else "-")
        marker = ""
        if s["signal"] in ("Strong Buy", "Buy"):
            marker = " ▲"
        elif s["signal"] in ("Strong Sell", "Sell"):
            marker = " ▼"
        print(
            f"  {rank:<4} {s['symbol']:<8} {s['signal']:<14} "
            f"{s['composite']:>+10.2f}  [{regime}]{marker}"
        )

    print(f"{'='*68}")
    print(f"  ✓ {len(successes)} signals written  |  {len(errors)} errors  |  {duration:.1f}s  |  run #{run_id}")
    if errors:
        print(f"  Skipped: {', '.join(errors)}")
    print(f"  DB → {_DB_PATH}")
    print()


if __name__ == "__main__":
    main()

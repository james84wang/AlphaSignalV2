#!/usr/bin/env python
"""Port-check: list every hidden_div BUY/SELL signal on AAPL daily (last 3 years).

Purpose: compare the Python port against the TradingView .pine on AAPL daily.
This prints — and writes to data/port_check/aapl_signals.csv — every confluence
BUY and SELL *signal event* (the same events the .pine plots as triangles), with
the bar date, the bar's close, the entry/exit score, and which components fired.

The signal *events* are what you eyeball against TradingView. The portfolio
backtest (entry at T+1 open, Top-N, ATR stops) is also run at the end just to
confirm the engine wires into the backtester — its trade dates legitimately sit a
bar or two after the signal dates.

Price basis: the backtester's price source — yfinance auto-adjusted (total-return)
daily closes (ParquetCache → YFinanceProvider). Use the SAME basis in TradingView.

Usage:
    uv run python scripts/port_check_aapl.py
    uv run python scripts/port_check_aapl.py --symbol MSFT --years 3
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.backtest.engine import run_backtest
from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.scoring.confluence import ENTRY_COMPONENTS, EXIT_COMPONENTS, run_engine

_WARMUP_DAYS = 420  # extra history so EMA200 + pivots are warm at the window start
_OUT = _REPO_ROOT / "data" / "port_check" / "aapl_signals.csv"
_COMPONENTS = list(ENTRY_COMPONENTS) + list(EXIT_COMPONENTS)


def main() -> None:
    ap = argparse.ArgumentParser(description="hidden_div signal port-check vs TradingView")
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--years", type=int, default=3, help="reporting window in years (default 3)")
    args = ap.parse_args()
    symbol = args.symbol.upper()

    cfg = load_config()
    end = date.today()
    window_start = end - timedelta(days=args.years * 365)
    fetch_start = window_start - timedelta(days=_WARMUP_DAYS)

    cache = ParquetCache(YFinanceProvider())
    print(f"Fetching {symbol} {fetch_start} → {end} (incl. {_WARMUP_DAYS}d warm-up)…", flush=True)
    df = cache.get_daily_bars(symbol, fetch_start, end)
    if df.empty:
        print(f"ERROR: no data for {symbol}", file=sys.stderr)
        sys.exit(1)

    results = run_engine(df, cfg)  # one auditable row per bar, oldest → newest
    closes = [float(df.iloc[i]["close"]) for i in range(len(df))]

    window_str = str(window_start)
    rows: list[dict] = []
    for i, r in enumerate(results):
        if r["date"] < window_str:
            continue  # warm-up region — not part of the reporting window
        if r["signal"] == "Hold":
            continue
        comp = r["components"]
        rows.append({
            "date": r["date"],
            "close": round(closes[i], 4),
            "signal": r["signal"],
            "entry_score": r["entry_score"],
            "exit_score": r["exit_score"],
            **{name: int(comp[name]["fired"]) for name in _COMPONENTS},
        })

    # ── Print ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  {symbol} — hidden_div signal events  ({window_start} → {end})  ·  {len(rows)} signals")
    print(f"{'='*100}")
    hdr = f"  {'date':<12}{'signal':<12}{'close':>10}{'entry':>7}{'exit':>7}   fired"
    print(hdr)
    print(f"  {'-'*96}")
    for row in rows:
        fired = [n for n in _COMPONENTS if row[n]]
        print(
            f"  {row['date']:<12}{row['signal']:<12}{row['close']:>10.2f}"
            f"{row['entry_score']:>7.0f}{row['exit_score']:>7.0f}   {', '.join(fired) or '—'}"
        )
    n_buy = sum(1 for r in rows if r["signal"] in ("Buy", "Strong Buy"))
    n_sell = sum(1 for r in rows if r["signal"] == "Sell")
    print(f"  {'-'*96}")
    print(f"  {n_buy} BUY · {n_sell} SELL")

    # ── CSV ────────────────────────────────────────────────────────────────────
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "close", "signal", "entry_score", "exit_score", *_COMPONENTS]
    with _OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  Signal list → {_OUT}")

    # ── Confirm it wires into the portfolio backtester ───────────────────────────
    def _fetch(sym, s, e):
        return cache.get_daily_bars(sym, s, e)

    bt = run_backtest([symbol], window_start, end, cfg, _fetch, strategy="hidden_div")
    m = bt.metrics
    print(f"\n  Portfolio backtest (sanity): {m.get('n_trades', 0)} trades, "
          f"sides={ {t.side for t in bt.trades} or '∅'}, "
          f"final=${m.get('final_equity', 0):,.0f}, benchmark={bt.params.get('benchmark_symbol')}")
    print("  (Trade dates sit a bar or two after the signal dates — expected.)\n")


if __name__ == "__main__":
    main()

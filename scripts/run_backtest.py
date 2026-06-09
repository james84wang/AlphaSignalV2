#!/usr/bin/env python
"""Run the long backtest and print a full performance report.

Usage (from repo root):
    uv run python scripts/run_backtest.py
    uv run python scripts/run_backtest.py --years 3 --account 50000
    uv run python scripts/run_backtest.py --no-save
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.config import load_config
from backend.app.data.cache import ParquetCache
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.backtest.engine import run_backtest
from backend.app.db.backtest_models import save_backtest_result
from backend.app.db.models import config_hash


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_watchlist(cfg) -> list[str]:
    wl_path = _REPO_ROOT / "data" / "watchlist.csv"
    if not wl_path.exists():
        logger.warning("No watchlist.csv — using default tickers")
        return ["SPY", "QQQ", "IWM", "DIA"]

    import pandas as pd
    df = pd.read_csv(wl_path)
    if "symbol" not in df.columns:
        logger.error("watchlist.csv missing 'symbol' column")
        return []
    symbols = df["symbol"].str.upper().dropna().tolist()
    logger.info("Loaded %d symbols from watchlist", len(symbols))
    return symbols


def _print_long_report(result, initial_account: float) -> None:
    m = result.metrics
    trades = result.trades
    sep = "─" * 62

    print(f"\n{'═' * 62}")
    print("  LONG PROFILE BACKTEST — AlphaSignalV2")
    print(f"{'═' * 62}")
    print(f"  Period : {result.params.get('start')} → {result.params.get('end')}")
    print(f"  Symbols: {result.params.get('n_symbols_loaded')} loaded")
    print(f"  Capital: ${initial_account:,.0f}")
    print(sep)

    print("\n  ── Performance Metrics ─────────────────────────────────")
    print(f"  CAGR              : {m.get('cagr', 0):+.1f}%")
    print(f"  Total Return      : {m.get('total_return_pct', 0):+.1f}%")
    print(f"  Final Equity      : ${m.get('final_equity', 0):,.2f}")
    print(f"  Sharpe Ratio      : {m.get('sharpe', 0):.3f}  (target > 1.0)")
    print(f"  Max Drawdown      : {m.get('max_drawdown_pct', 0):.1f}%  (target < 20%)")
    print(f"  Exposure          : {m.get('exposure_pct', 0):.1f}% of trading days")

    print("\n  ── Trade Statistics ────────────────────────────────────")
    print(f"  Total Trades      : {m.get('n_trades', 0)}")
    print(f"  Symbols Traded    : {m.get('n_symbols', 0)}")
    print(f"  Hit Rate          : {m.get('hit_rate', 0)*100:.1f}%")
    print(f"  Avg Win           : ${m.get('avg_win', 0):+.2f}")
    print(f"  Avg Loss          : ${m.get('avg_loss', 0):+.2f}")
    print(f"  Profit Factor     : {m.get('profit_factor', 0):.2f}")

    _print_viability(m)
    _print_trade_log(trades, sep)
    _print_equity_summary(result)

    print(f"\n  {result.survivorship_note}")
    print(f"\n{'═' * 62}\n")


def _print_viability(m: dict) -> None:
    sharpe = m.get("sharpe", 0.0)
    maxdd = m.get("max_drawdown_pct", 0.0)
    sharpe_ok = sharpe > 1.0
    dd_ok = maxdd < 20.0
    viable = sharpe_ok and dd_ok

    print(f"\n  ── Viability Assessment ────────────────────────────────")
    print(f"  Sharpe > 1.0      : {'PASS' if sharpe_ok else 'FAIL'}  ({sharpe:.3f})")
    print(f"  MaxDD < 20%       : {'PASS' if dd_ok else 'FAIL'}  ({maxdd:.1f}%)")
    print(f"  Overall           : {'VIABLE' if viable else 'NOT VIABLE'}")


def _print_trade_log(trades, sep: str) -> None:
    if not trades:
        return
    n = min(10, len(trades))
    print(f"\n  ── Trade Log (showing {n} of {len(trades)}) ─────────────────")
    print(f"  {'Symbol':<10} {'Side':<6} {'Entry':>10} {'Exit':>10} {'P&L':>9} {'%':>7} {'Reason'}")
    print("  " + sep)
    for t in sorted(trades, key=lambda x: abs(x.pnl), reverse=True)[:n]:
        print(
            f"  {t.symbol:<10} {t.side:<6} {t.entry_date:>10} {t.exit_date:>10} "
            f"  {t.pnl:+9.2f} {t.pnl_pct:+7.2f}% {t.exit_reason}"
        )


def _print_equity_summary(result) -> None:
    if not result.equity_curve:
        return
    equities = [e["equity"] for e in result.equity_curve]
    print(f"\n  ── Equity Curve Summary ────────────────────────────────")
    print(f"  Start : ${equities[0]:,.2f}  ({result.equity_curve[0]['date']})")
    print(f"  End   : ${equities[-1]:,.2f}  ({result.equity_curve[-1]['date']})")
    print(f"  Peak  : ${max(equities):,.2f}")
    print(f"  Trough: ${min(equities):,.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AlphaSignalV2 Long Backtest Runner")
    parser.add_argument(
        "--strategy",
        choices=["hidden_div"],
        default="hidden_div",
        help="Strategy profile (long-only Hidden-Divergence Confluence).",
    )
    parser.add_argument("--years", type=int, default=None, help="Years of history (default: config)")
    parser.add_argument("--account", type=float, default=None, help="Starting capital (default: config)")
    parser.add_argument("--no-save", action="store_true", help="Skip SQLite persistence")
    args = parser.parse_args()

    cfg = load_config()
    years = args.years or cfg.backtest.start_years_back
    initial_account = args.account or cfg.backtest.initial_account

    end = date.today()
    start = end - timedelta(days=years * 365)

    symbols = _load_watchlist(cfg)
    if not symbols:
        logger.error("No symbols to backtest — exiting")
        sys.exit(1)

    provider = YFinanceProvider()
    cache = ParquetCache(provider)

    def _fetcher(sym: str, s: date, e: date):
        return cache.get_daily_bars(sym, s, e)

    logger.info(
        "Starting %s backtest: %d symbols, %s → %s, $%.0f initial",
        args.strategy, len(symbols), start, end, initial_account,
    )

    t0 = time.perf_counter()
    result = run_backtest(
        symbols=symbols,
        start=start,
        end=end,
        cfg=cfg,
        data_fetcher=_fetcher,
        strategy=args.strategy,
        initial_account=initial_account,
    )
    duration = time.perf_counter() - t0

    _print_long_report(result, initial_account)

    if not args.no_save and result.trades:
        cfg_hash_val = config_hash(_REPO_ROOT / "config.yaml")
        run_id = save_backtest_result(result, cfg_hash_val, duration)
        print(f"  Saved to SQLite — backtest_run id={run_id}")
    else:
        if not result.trades:
            print("  (no trades to save)")

    logger.info("Done in %.1f s", duration)

    print("\n  ─── HOW TO RE-RUN ─────────────────────────────────────")
    print("    uv run python scripts/run_backtest.py")
    print()


if __name__ == "__main__":
    main()

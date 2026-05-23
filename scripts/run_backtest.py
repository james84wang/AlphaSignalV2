#!/usr/bin/env python
"""Run a profile backtest and print a full performance report.

Usage (from repo root):
    # Long profile — signal and trade on the underlying
    uv run python scripts/run_backtest.py --strategy long

    # Short profile — signal on underlying, trade on actual inverse ETF
    uv run python scripts/run_backtest.py --strategy short

    # Common options
    uv run python scripts/run_backtest.py --years 3 --account 50000
    uv run python scripts/run_backtest.py --strategy short --no-save

One command per acceptance criterion (spec phase-4.md, MOD-E).
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


def _print_short_report(result, initial_account: float) -> None:
    m = result.metrics
    trades = result.trades
    sep = "─" * 62

    print(f"\n{'═' * 62}")
    print("  SHORT PROFILE BACKTEST — AlphaSignalV2")
    print("  (Signal: underlying short profile; Trade: inverse ETF)")
    print(f"{'═' * 62}")
    print(f"  Period : {result.params.get('start')} → {result.params.get('end')}")
    print(f"  Symbols: {result.params.get('n_symbols_loaded')} testable on short side")
    print(f"  Capital: ${initial_account:,.0f}")

    caveats = result.params.get("caveats", [])
    if caveats:
        print("\n  ── Honest Caveats ──────────────────────────────────────")
        for c in caveats:
            print(f"  ⚠  {c}")
    print(sep)

    print("\n  ── Performance Metrics (on real inverse ETF prices) ────")
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

    # ── Decay diagnostic ─────────────────────────────────────────────────────
    short_trades = [t for t in trades if t.synthetic_pnl is not None]
    if short_trades:
        print("\n  ── Decay Diagnostic (real ETF vs. synthetic inverse) ───")
        print(f"  {'Underlying→ETF':<18} {'Entry':>10} {'Exit':>10} "
              f"  {'Real P&L':>9} {'Synth P&L':>10}  {'Decay Drag':>10}")
        print("  " + sep)
        shown = short_trades[:8]
        for t in shown:
            label = f"{t.underlying_symbol}→{t.trade_instrument}"
            drag = (t.pnl or 0) - (t.synthetic_pnl or 0)
            print(
                f"  {label:<18} {t.entry_date:>10} {t.exit_date:>10} "
                f"  {t.pnl:+9.2f} {t.synthetic_pnl:+10.2f}  {drag:+10.2f}"
            )
        if len(short_trades) > 8:
            print(f"  … {len(short_trades) - 8} more trades not shown")

        total_real = sum(t.pnl for t in short_trades)
        total_synth = sum(t.synthetic_pnl for t in short_trades)
        total_drag = total_real - total_synth
        print("  " + sep)
        print(
            f"  {'TOTAL':<18} {'':>10} {'':>10} "
            f"  {total_real:+9.2f} {total_synth:+10.2f}  {total_drag:+10.2f}"
        )
        print(f"\n  Decay drag = real ETF P&L minus synthetic (−1× underlying).")
        print(f"  Negative drag means the inverse ETF underperformed the synthetic short.")
    else:
        print("\n  (No short trades with synthetic comparison available)")

    _print_trade_log(trades, sep)
    _print_equity_summary(result)

    # ── Coverage report ───────────────────────────────────────────────────────
    if result.coverage_report is not None:
        cr = result.coverage_report
        s = cr.summary
        print(f"\n  ── Coverage Report ─────────────────────────────────────")
        print(f"  Universe size     : {s['universe_size']}")
        print(f"  Testable names    : {s['n_testable']} ({s['pct_testable']}%)")
        print(f"  Avg window        : {s['avg_tested_window_days']/365:.1f} yrs "
              f"({s['avg_tested_window_days']} days)")

        if cr.tested:
            print(f"\n  Tested ({len(cr.tested)}):")
            for t in cr.tested:
                note = (
                    f"  [{t.skipped_signals_before_etf_launch} signals pre-ETF skipped]"
                    if t.skipped_signals_before_etf_launch > 0 else ""
                )
                print(
                    f"    {t.underlying}→{t.inverse_etf}: "
                    f"{t.window_tested_start}–{t.window_tested_end} "
                    f"({t.n_trades} trades){note}"
                )
        if cr.skipped_no_instrument:
            print(f"\n  No inverse ETF ({len(cr.skipped_no_instrument)}): "
                  + ", ".join(cr.skipped_no_instrument[:10])
                  + (" …" if len(cr.skipped_no_instrument) > 10 else ""))
        if cr.skipped_insufficient_history:
            print(f"\n  Insufficient history ({len(cr.skipped_insufficient_history)}):")
            for e in cr.skipped_insufficient_history:
                print(f"    {e.underlying}→{e.inverse_etf}: {e.reason}")
        if cr.skipped_data_error:
            print(f"\n  Data errors ({len(cr.skipped_data_error)}):")
            for e in cr.skipped_data_error:
                print(f"    {e.symbol}: {e.error}")

        _print_short_honesty_assessment(cr)

    print(f"\n  {result.survivorship_note}")
    print(f"\n{'═' * 62}\n")


def _print_short_honesty_assessment(cr) -> None:
    """Honest plain-English assessment of short-side testability."""
    s = cr.summary
    print(f"\n  ── Honest Assessment ───────────────────────────────────")
    if s["n_testable"] == 0:
        print("  NO names are testable on the short side with current data.")
        print("  Add inverse ETF mappings in data/inverse_etfs.csv to enable testing.")
        return

    avg_yrs = s["avg_tested_window_days"] / 365
    if avg_yrs < 2:
        conclusion = "INSUFFICIENT history to draw conclusions (< 2 years average)"
    elif avg_yrs < 3:
        conclusion = "MARGINAL history — treat results with caution (< 3 years)"
    else:
        conclusion = "ADEQUATE history for preliminary conclusions (≥ 3 years)"

    print(f"  {s['n_testable']} of {s['universe_size']} names are testable")
    print(f"  ({s['pct_testable']}% of requested universe).")
    print(f"  Average usable window: {avg_yrs:.1f} years.")
    print(f"  Verdict: {conclusion}.")


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
    parser = argparse.ArgumentParser(description="AlphaSignalV2 Per-Profile Backtest Runner")
    parser.add_argument(
        "--strategy",
        choices=["long", "short"],
        default="long",
        help="Which profile to backtest: 'long' (default) or 'short' (trades inverse ETF)",
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

    if args.strategy == "short":
        _print_short_report(result, initial_account)
    else:
        _print_long_report(result, initial_account)

    if not args.no_save and (result.trades or result.coverage_report):
        cfg_hash_val = config_hash(_REPO_ROOT / "config.yaml")
        run_id = save_backtest_result(result, cfg_hash_val, duration)
        print(f"  Saved to SQLite — backtest_run id={run_id}")
    else:
        if not result.trades:
            print("  (no trades to save)")

    logger.info("Done in %.1f s", duration)

    # Print the exact commands per acceptance criterion
    print("\n  ─── HOW TO RE-RUN ─────────────────────────────────────")
    print("  Long profile:")
    print("    uv run python scripts/run_backtest.py --strategy long")
    print("  Short profile:")
    print("    uv run python scripts/run_backtest.py --strategy short")
    print("  Read coverage report: included in the short-profile output above.")
    print()


if __name__ == "__main__":
    main()

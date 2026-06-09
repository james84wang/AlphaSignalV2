"""Performance metrics for a completed backtest run. MOD-F extended set.

Strategy metrics (full set):
  n_trades, n_symbols, win_rate (=hit_rate), avg_win, avg_loss, win_loss_ratio,
  profit_factor, max_drawdown (max_drawdown_pct), sharpe_ratio (sharpe),
  exposure_pct, cagr, total_return (total_return_pct), final_equity,
  turnover, avg_holding_days.

Benchmark metrics (5-metric subset, same names):
  total_return, cagr, sharpe_ratio, max_drawdown, final_equity.

Sharpe convention: daily returns, annualised by ×√252, risk_free_rate from config
(default 0). Applied identically to strategy and benchmark.
"""
from __future__ import annotations

import math
from datetime import date as dt
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backend.app.backtest.engine import ClosedTrade
    from backend.app.config import BacktestConfig


def compute_strategy_metrics(
    trades: list["ClosedTrade"],
    equity_curve: list[dict],
    initial_fund: float,
    risk_free_rate: float = 0.0,
) -> dict:
    """Full strategy metric set. Returns both old and new metric names for compat."""
    m: dict = {}
    m["n_trades"] = len(trades)
    m["n_symbols"] = len({t.symbol for t in trades}) if trades else 0

    if not trades:
        m.update(
            win_rate=0.0, hit_rate=0.0,
            avg_win=0.0, avg_loss=0.0, win_loss_ratio=0.0, profit_factor=0.0,
            max_drawdown=0.0, max_drawdown_pct=0.0,
            sharpe_ratio=0.0, sharpe=0.0,
            exposure_pct=0.0,
            cagr=0.0,
            total_return=0.0, total_return_pct=0.0,
            final_equity=float(initial_fund),
            turnover=0.0,
            avg_holding_days=0.0,
            total_fees=0.0,
        )
        return m

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls)
    m["win_rate"] = round(win_rate, 4)
    m["hit_rate"] = m["win_rate"]  # backward-compat alias

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    m["avg_win"] = round(avg_win, 2)
    m["avg_loss"] = round(avg_loss, 2)
    m["win_loss_ratio"] = round(avg_win / abs(avg_loss), 4) if avg_loss < 0 else float("inf")

    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    if sum_losses > 0:
        m["profit_factor"] = round(sum_wins / sum_losses, 4)
    elif sum_wins > 0:
        m["profit_factor"] = float("inf")
    else:
        m["profit_factor"] = 0.0

    # Total fees paid
    total_fees = sum(
        getattr(t, "entry_fee", 0.0) + getattr(t, "exit_fee", 0.0) for t in trades
    )
    m["total_fees"] = round(total_fees, 2)

    if not equity_curve:
        m.update(
            max_drawdown=0.0, max_drawdown_pct=0.0,
            sharpe_ratio=0.0, sharpe=0.0,
            exposure_pct=0.0, cagr=0.0,
            total_return=0.0, total_return_pct=0.0,
            final_equity=float(initial_fund),
            turnover=0.0, avg_holding_days=0.0,
        )
        return m

    equities = [e["equity"] for e in equity_curve]
    final_eq = equities[-1]
    m["final_equity"] = round(final_eq, 2)
    total_return = (final_eq - initial_fund) / initial_fund * 100
    m["total_return"] = round(total_return, 2)
    m["total_return_pct"] = m["total_return"]  # alias

    # Max drawdown
    peak = float(initial_fund)
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    m["max_drawdown"] = round(max_dd * 100, 2)
    m["max_drawdown_pct"] = m["max_drawdown"]  # alias

    # CAGR
    n_years = len(equity_curve) / 252
    if n_years > 0 and final_eq > 0 and initial_fund > 0:
        m["cagr"] = round(((final_eq / initial_fund) ** (1.0 / n_years) - 1) * 100, 2)
    else:
        m["cagr"] = 0.0

    # Sharpe: daily returns annualised, risk-free deducted per day
    daily_rf = risk_free_rate / 252
    ret = pd.Series(equities).pct_change().dropna() - daily_rf
    if len(ret) > 1 and ret.std() > 0:
        sharpe = float(ret.mean() / ret.std() * math.sqrt(252))
        m["sharpe_ratio"] = round(sharpe, 4)
    else:
        m["sharpe_ratio"] = 0.0
    m["sharpe"] = m["sharpe_ratio"]  # alias

    # Sortino: downside deviation (std of negative returns only)
    downside = ret[ret < 0]
    if len(downside) > 1 and downside.std() > 0:
        m["sortino_ratio"] = round(float(ret.mean() / downside.std() * math.sqrt(252)), 4)
    else:
        m["sortino_ratio"] = 0.0

    # Exposure: average % of equity deployed (weighted by equity)
    n_open_vals = [e.get("n_open", 0) for e in equity_curve]
    exposed_days = sum(1 for n in n_open_vals if n > 0)
    m["exposure_pct"] = round(exposed_days / len(equity_curve) * 100, 2)

    # Turnover: annualised gross volume / average equity
    total_volume = sum(
        t.shares * t.entry_price + t.shares * abs(t.exit_price)
        for t in trades
    )
    avg_equity = sum(equities) / len(equities) if equities else initial_fund
    n_days = len(equity_curve)
    if avg_equity > 0 and n_days > 0:
        m["turnover"] = round((total_volume / avg_equity) * (252 / n_days), 4)
    else:
        m["turnover"] = 0.0

    # Average holding period in calendar days
    holding_days = []
    for t in trades:
        try:
            entry = dt.fromisoformat(t.entry_date)
            exit_ = dt.fromisoformat(t.exit_date)
            holding_days.append((exit_ - entry).days)
        except Exception:
            pass
    m["avg_holding_days"] = round(sum(holding_days) / len(holding_days), 1) if holding_days else 0.0

    return m


def compute_benchmark_metrics(
    equity_curve: list[dict],
    initial_fund: float,
    risk_free_rate: float = 0.0,
) -> dict:
    """5-metric set for the buy-and-hold benchmark."""
    if not equity_curve:
        return {
            "total_return": 0.0, "cagr": 0.0, "sharpe_ratio": 0.0,
            "max_drawdown": 0.0, "final_equity": float(initial_fund),
        }

    equities = [e["equity"] for e in equity_curve]
    final_eq = equities[-1]

    total_return = (final_eq - initial_fund) / initial_fund * 100

    peak = float(initial_fund)
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    n_years = len(equity_curve) / 252
    if n_years > 0 and final_eq > 0 and initial_fund > 0:
        cagr = ((final_eq / initial_fund) ** (1.0 / n_years) - 1) * 100
    else:
        cagr = 0.0

    daily_rf = risk_free_rate / 252
    ret = pd.Series(equities).pct_change().dropna() - daily_rf
    if len(ret) > 1 and ret.std() > 0:
        sharpe = float(ret.mean() / ret.std() * math.sqrt(252))
    else:
        sharpe = 0.0

    downside = ret[ret < 0]
    if len(downside) > 1 and downside.std() > 0:
        sortino = float(ret.mean() / downside.std() * math.sqrt(252))
    else:
        sortino = 0.0

    return {
        "total_return": round(total_return, 2),
        "cagr": round(cagr, 2),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown": round(max_dd * 100, 2),
        "final_equity": round(final_eq, 2),
    }


def build_comparison(
    strategy_metrics: dict,
    benchmark_metrics: dict,
    bk: "BacktestConfig",
) -> dict:
    """Build side-by-side strategy vs benchmark comparison for the 5 shared metrics."""
    shared_keys = ["total_return", "cagr", "sharpe_ratio", "max_drawdown", "final_equity"]
    rows = {}
    for k in shared_keys:
        rows[k] = {
            "strategy": strategy_metrics.get(k),
            "benchmark": benchmark_metrics.get(k),
        }

    max_slots = bk.max_concurrent_positions
    size_pct = bk.position_size_pct
    max_deployed = min(max_slots * size_pct, 1.0)

    fairness_caveat = (
        f"FAIRNESS CAVEAT: The strategy deploys at most {max_slots} × {size_pct:.0%} = "
        f"{max_deployed:.0%} of equity across many names (capped by available cash), "
        f"while the benchmark is 100% in one instrument. Compare primarily on Sharpe and "
        f"max drawdown, not raw return alone."
    )

    return {
        "metrics": rows,
        "fairness_caveat": fairness_caveat,
        "sharpe_convention": (
            "Daily returns, annualised by ×√252, risk_free_rate from config (default 0). "
            "Applied identically to strategy and benchmark."
        ),
        "price_basis": (
            "Adjusted / total-return prices (dividends included) via yfinance auto_adjust=True "
            "for both strategy instruments and benchmark."
        ),
    }


def compute_metrics(
    trades: list["ClosedTrade"],
    equity_curve: list[dict],
    initial_account: float,
) -> dict:
    """Backward-compat wrapper. Delegates to compute_strategy_metrics."""
    return compute_strategy_metrics(trades, equity_curve, initial_account)

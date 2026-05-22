"""Performance metrics for a completed backtest run.

Implements spec §6.5 success targets:
  Sharpe > 1.0, max drawdown < 20% over 5 years.

Metrics returned:
  n_trades, n_symbols, hit_rate, avg_win, avg_loss, profit_factor,
  max_drawdown_pct, sharpe, exposure_pct, cagr, total_return_pct, final_equity.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backend.app.backtest.engine import ClosedTrade


def compute_metrics(
    trades: list["ClosedTrade"],
    equity_curve: list[dict],
    initial_account: float,
) -> dict:
    """Compute performance metrics from closed trades and a daily equity curve.

    equity_curve: [{"date": "YYYY-MM-DD", "equity": float, "n_open": int}, ...]
    """
    m: dict = {}
    m["n_trades"] = len(trades)
    m["n_symbols"] = len({t.symbol for t in trades}) if trades else 0

    # ── Win/loss stats ────────────────────────────────────────────────────────
    if not trades:
        m.update(
            hit_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            sharpe=0.0,
            exposure_pct=0.0,
            cagr=0.0,
            total_return_pct=0.0,
            final_equity=float(initial_account),
        )
        return m

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    m["hit_rate"] = round(len(wins) / len(pnls), 4)
    m["avg_win"] = round(sum(wins) / len(wins), 2) if wins else 0.0
    m["avg_loss"] = round(sum(losses) / len(losses), 2) if losses else 0.0

    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    if sum_losses > 0:
        m["profit_factor"] = round(sum_wins / sum_losses, 4)
    elif sum_wins > 0:
        m["profit_factor"] = float("inf")
    else:
        m["profit_factor"] = 0.0

    # ── Equity curve stats ────────────────────────────────────────────────────
    if not equity_curve:
        m.update(
            max_drawdown_pct=0.0,
            sharpe=0.0,
            exposure_pct=0.0,
            cagr=0.0,
            total_return_pct=0.0,
            final_equity=float(initial_account),
        )
        return m

    equities = [e["equity"] for e in equity_curve]
    final_eq = equities[-1]
    m["final_equity"] = round(final_eq, 2)
    m["total_return_pct"] = round((final_eq - initial_account) / initial_account * 100, 2)

    # Max drawdown: peak-to-trough on the equity curve
    peak = float(initial_account)
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    m["max_drawdown_pct"] = round(max_dd * 100, 2)

    # CAGR: uses trading-day count / 252 as year estimate
    n_years = len(equity_curve) / 252
    if n_years > 0 and final_eq > 0 and initial_account > 0:
        m["cagr"] = round(((final_eq / initial_account) ** (1.0 / n_years) - 1) * 100, 2)
    else:
        m["cagr"] = 0.0

    # Sharpe: annualised, daily returns, risk-free = 0
    ret = pd.Series(equities).pct_change().dropna()
    if len(ret) > 1 and ret.std() > 0:
        m["sharpe"] = round(float(ret.mean() / ret.std() * math.sqrt(252)), 4)
    else:
        m["sharpe"] = 0.0

    # Exposure: % of days with ≥ 1 open position
    n_open_vals = [e.get("n_open", 0) for e in equity_curve]
    exposed_days = sum(1 for n in n_open_vals if n > 0)
    m["exposure_pct"] = round(exposed_days / len(equity_curve) * 100, 2)

    return m

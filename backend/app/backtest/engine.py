"""Walk-forward backtest engine. Implements spec §6.5 and §7 defaults.

Critical invariant (no look-ahead):
  Signal at bar T is computed from data[0..T] only.
  Entry fills at bar T+1's open price.
  Stop and signal exits also fill at the next bar's open or at the stop price intrabar.

Why pre-computing signals over the full DataFrame is safe:
  run_engine() uses only rolling/backward-looking operations (EMA, MACD, RSI, ATR,
  swing pivots, S/R clustering). Each row's output is a pure function of that row and
  earlier rows — no peek at future rows occurs. The no-look-ahead unit tests in
  test_composite.py prove this for the scoring layer.

Survivorship bias limitation:
  If the supplied symbol list is the CURRENT S&P 500 membership, companies that were
  delisted or removed during the backtest period are absent. This inflates results.
  See SURVIVORSHIP_BIAS_NOTE below.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from backend.app.config import AppConfig
from backend.app.indicators.atr import compute_atr
from backend.app.scoring.composite import run_engine as _compute_signals

logger = logging.getLogger(__name__)

SURVIVORSHIP_BIAS_NOTE = (
    "SURVIVORSHIP BIAS WARNING: The universe list reflects CURRENT index membership. "
    "Companies delisted, acquired, or removed during the backtest period are absent. "
    "This inflates all performance metrics — treat them as an upper bound."
)

DataFetcher = Callable[[str, date, date], pd.DataFrame]


# ── Public data structures ─────────────────────────────────────────────────────

@dataclass
class ClosedTrade:
    symbol: str
    side: str               # "long" | "short"
    entry_date: str         # ISO YYYY-MM-DD
    entry_price: float
    exit_date: str
    exit_price: float
    shares: float
    initial_stop: float     # stop at entry
    pnl: float              # net P&L after both commissions
    pnl_pct: float          # pnl / (entry_price * shares)
    exit_reason: str        # "stop" | "signal" | "end_of_data"


@dataclass
class BacktestResult:
    metrics: dict
    trades: list[ClosedTrade]
    equity_curve: list[dict]    # [{"date", "equity", "n_open"}, ...]
    params: dict
    survivorship_note: str = field(default=SURVIVORSHIP_BIAS_NOTE)


# ── Internal data structures ───────────────────────────────────────────────────

@dataclass
class _SymbolData:
    dates: list[date]
    bars: dict[date, dict]      # date → {open, high, low, close}
    signals: dict[date, dict]   # date → run_engine output row
    atr: dict[date, float]      # date → ATR value


@dataclass
class _Position:
    symbol: str
    side: str
    entry_date: str
    entry_price: float
    shares: float
    stop_price: float


@dataclass
class _PendingEntry:
    side: str
    atr_at_signal: float
    signal_date: str


# ── Engine ─────────────────────────────────────────────────────────────────────

def run_backtest(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    initial_account: float | None = None,
    slippage_pct: float | None = None,
    commission: float | None = None,
) -> BacktestResult:
    """Run a walk-forward backtest over *symbols* from *start* to *end*.

    None-valued parameters fall back to cfg.backtest defaults.

    Args:
        symbols: ticker list (e.g. ["AAPL", "MSFT"])
        start:   backtest start date (inclusive)
        end:     backtest end date (inclusive)
        cfg:     loaded AppConfig (weights, risk rules, etc.)
        data_fetcher: callable(symbol, start, end) → OHLCV DataFrame
        initial_account: starting portfolio value in USD
        slippage_pct: fraction of fill price lost to slippage (both entry and exit)
        commission:   flat dollar commission per fill

    Returns:
        BacktestResult with metrics, trade log, equity curve, and params snapshot.

    Note: earnings blackout (cfg.risk.earnings_blackout_bars) requires a Finnhub
    earnings calendar key (FINNHUB_API_KEY env var). Without it, this rule is
    silently skipped — all signals are considered regardless of proximity to earnings.
    """
    if initial_account is None:
        initial_account = cfg.backtest.initial_account
    if slippage_pct is None:
        slippage_pct = cfg.backtest.slippage_pct
    if commission is None:
        commission = cfg.backtest.commission_per_trade

    # ── 1. Load and pre-compute per-symbol data ────────────────────────────────
    sym_data: dict[str, _SymbolData] = {}
    for sym in symbols:
        sd = _load_symbol(sym, start, end, cfg, data_fetcher)
        if sd is not None:
            sym_data[sym] = sd

    if not sym_data:
        logger.error("No symbols loaded — aborting backtest")
        return BacktestResult({}, [], [], {"error": "no symbols loaded"})

    # ── 2. Build unified date series ───────────────────────────────────────────
    all_dates: list[date] = sorted({d for sd in sym_data.values() for d in sd.dates})

    # ── 3. State ───────────────────────────────────────────────────────────────
    cash = float(initial_account)
    open_pos: dict[str, _Position] = {}
    pending_entries: dict[str, _PendingEntry] = {}
    pending_exits: set[str] = set()         # signal-flip exits → fill at today's open
    cooldowns: dict[str, int] = {}          # symbol → bars remaining after stop-out
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[dict] = []

    # ── 4. Walk day by day ─────────────────────────────────────────────────────
    for day_idx, today in enumerate(all_dates):

        # a. Fill pending signal-exits at today's open (scheduled yesterday)
        for sym in list(pending_exits):
            if sym in open_pos and sym in sym_data and today in sym_data[sym].bars:
                bar = sym_data[sym].bars[today]
                cash = _close_pos(
                    sym, bar["open"], str(today), "signal",
                    open_pos, closed_trades, commission, slippage_pct, cash,
                )
                # no cooldown on signal exits
        pending_exits.clear()

        # b. Fill pending entries at today's open (scheduled yesterday)
        for sym in list(pending_entries.keys()):
            pe = pending_entries[sym]
            if sym not in sym_data or today not in sym_data[sym].bars:
                del pending_entries[sym]
                continue
            bar = sym_data[sym].bars[today]

            acct = _account_value(cash, open_pos, sym_data, today)
            slip_mult = (1 + slippage_pct) if pe.side == "long" else (1 - slippage_pct)
            entry_p = bar["open"] * slip_mult

            risk_per_share = cfg.risk.stop_loss_atr_mult * pe.atr_at_signal
            if risk_per_share > 0:
                shares = (acct * cfg.risk.position_size_pct) / risk_per_share
                # Limit to available cash for longs
                if pe.side == "long":
                    max_shares = max(0.0, (cash - commission) / entry_p) if entry_p > 0 else 0.0
                    shares = min(shares, max_shares)
                else:
                    # Short: need commission in cash at minimum
                    if cash < commission:
                        shares = 0.0

                if shares > 0.01:  # ignore dust
                    if pe.side == "long":
                        stop_p = entry_p - cfg.risk.stop_loss_atr_mult * pe.atr_at_signal
                    else:
                        stop_p = entry_p + cfg.risk.stop_loss_atr_mult * pe.atr_at_signal

                    open_pos[sym] = _Position(
                        symbol=sym,
                        side=pe.side,
                        entry_date=str(today),
                        entry_price=entry_p,
                        shares=shares,
                        stop_price=stop_p,
                    )
                    if pe.side == "long":
                        cash -= shares * entry_p + commission
                    else:
                        cash += shares * entry_p - commission

                    logger.debug(
                        "[%s] %s entry %.4f shares @ %.2f stop=%.2f",
                        sym, pe.side, shares, entry_p, stop_p,
                    )
            del pending_entries[sym]

        # c. Check intrabar stops for open positions
        for sym in list(open_pos.keys()):
            if sym not in sym_data or today not in sym_data[sym].bars:
                continue
            pos = open_pos[sym]
            if pos.entry_date == str(today):
                continue  # no stop check on entry bar
            bar = sym_data[sym].bars[today]
            stop_hit, fill_p = _check_stop(pos, bar)
            if stop_hit:
                cash = _close_pos(
                    sym, fill_p, str(today), "stop",
                    open_pos, closed_trades, commission, 0.0, cash,
                )
                cooldowns[sym] = cfg.risk.reentry_cooldown_bars

        # d. Signal analysis for open positions and potential new entries
        n_open = len(open_pos)
        for sym, sd in sym_data.items():
            if today not in sd.signals:
                continue

            sig_result = sd.signals[today]
            signal = sig_result["signal"]
            atr_today = sd.atr.get(today, 0.0)

            # Update trailing stop on open positions
            if sym in open_pos and open_pos[sym].entry_date != str(today):
                if today in sd.bars:
                    _update_trailing_stop(open_pos[sym], sd.bars[today], atr_today, cfg)

            # Decrement cooldown
            if sym in cooldowns:
                cooldowns[sym] -= 1
                if cooldowns[sym] <= 0:
                    del cooldowns[sym]

            is_buy = signal in ("Buy", "Strong Buy")
            is_sell = signal in ("Sell", "Strong Sell")

            # Exit existing positions on opposite signal
            if sym in open_pos:
                pos = open_pos[sym]
                if (pos.side == "long" and is_sell) or (pos.side == "short" and is_buy):
                    if day_idx + 1 < len(all_dates):
                        pending_exits.add(sym)
                    else:
                        # Last bar: close at close price
                        close_p = sd.bars[today]["close"] if today in sd.bars else pos.entry_price
                        cash = _close_pos(
                            sym, close_p, str(today), "signal",
                            open_pos, closed_trades, commission, slippage_pct, cash,
                        )

            # New entries — only if a next bar exists and we have room
            elif (
                sym not in pending_entries
                and sym not in cooldowns
                and n_open + len(pending_entries) < cfg.risk.max_concurrent_positions
                and day_idx + 1 < len(all_dates)
            ):
                if is_buy:
                    pending_entries[sym] = _PendingEntry("long", atr_today, str(today))
                elif is_sell:
                    pending_entries[sym] = _PendingEntry("short", atr_today, str(today))

        # e. Record end-of-day equity
        acct = _account_value(cash, open_pos, sym_data, today)
        equity_curve.append({"date": str(today), "equity": round(acct, 2), "n_open": len(open_pos)})

    # ── 5. Close all remaining positions at last close ─────────────────────────
    last_date = all_dates[-1]
    for sym in list(open_pos.keys()):
        if sym in sym_data and last_date in sym_data[sym].bars:
            close_p = sym_data[sym].bars[last_date]["close"]
            cash = _close_pos(
                sym, close_p, str(last_date), "end_of_data",
                open_pos, closed_trades, commission, slippage_pct, cash,
            )
        else:
            pos = open_pos.pop(sym)
            # No data — record at entry price (zero P&L)
            closed_trades.append(_make_trade(pos, pos.entry_price, str(last_date), "end_of_data", commission, slippage_pct))

    # ── 6. Compute metrics ─────────────────────────────────────────────────────
    from backend.app.backtest.metrics import compute_metrics
    metrics = compute_metrics(closed_trades, equity_curve, initial_account)

    params = {
        "start": str(start),
        "end": str(end),
        "symbols": symbols,
        "n_symbols_loaded": len(sym_data),
        "initial_account": initial_account,
        "slippage_pct": slippage_pct,
        "commission": commission,
        "earnings_blackout": "disabled — FINNHUB_API_KEY not present",
    }

    logger.info(
        "Backtest complete: %d trades, Sharpe=%.2f, maxDD=%.1f%%, CAGR=%.1f%%",
        metrics.get("n_trades", 0),
        metrics.get("sharpe", 0.0),
        metrics.get("max_drawdown_pct", 0.0),
        metrics.get("cagr", 0.0),
    )
    return BacktestResult(metrics=metrics, trades=closed_trades, equity_curve=equity_curve, params=params)


# ── Private helpers ────────────────────────────────────────────────────────────

def _load_symbol(
    sym: str,
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
) -> _SymbolData | None:
    """Fetch OHLCV data and pre-compute signals + ATR for one symbol."""
    try:
        df = data_fetcher(sym, start, end)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] fetch failed: %s — skipping", sym, exc)
        return None

    if len(df) < 50:
        logger.warning("[%s] only %d bars — need ≥ 50, skipping", sym, len(df))
        return None

    signals_list = _compute_signals(df, cfg)
    atr_s = compute_atr(df, cfg.risk.stop_loss_atr_period)

    dates: list[date] = []
    bars: dict[date, dict] = {}
    signals: dict[date, dict] = {}
    atr: dict[date, float] = {}

    for i, (idx, row) in enumerate(df.iterrows()):
        d = idx.date() if hasattr(idx, "date") else idx
        dates.append(d)
        bars[d] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        signals[d] = signals_list[i]
        atr[d] = float(atr_s.iat[i]) if not pd.isna(atr_s.iat[i]) else 0.0

    return _SymbolData(dates=dates, bars=bars, signals=signals, atr=atr)


def _check_stop(pos: _Position, bar: dict) -> tuple[bool, float]:
    """Return (stop_hit, fill_price) using intrabar high/low. Spec §7 note."""
    if pos.side == "long":
        if bar["open"] <= pos.stop_price:
            return True, bar["open"]   # gap-down through stop
        if bar["low"] <= pos.stop_price:
            return True, pos.stop_price
    else:  # short
        if bar["open"] >= pos.stop_price:
            return True, bar["open"]   # gap-up through stop
        if bar["high"] >= pos.stop_price:
            return True, pos.stop_price
    return False, 0.0


def _update_trailing_stop(pos: _Position, bar: dict, atr: float, cfg: AppConfig) -> None:
    """Move stop in the favourable direction using today's close and ATR."""
    if atr <= 0:
        return
    if pos.side == "long":
        new_stop = bar["close"] - cfg.risk.trail_stop_atr_mult * atr
        if new_stop > pos.stop_price:
            pos.stop_price = new_stop
    else:
        new_stop = bar["close"] + cfg.risk.trail_stop_atr_mult * atr
        if new_stop < pos.stop_price:
            pos.stop_price = new_stop


def _make_trade(
    pos: _Position,
    fill_price: float,
    exit_date: str,
    reason: str,
    commission: float,
    slippage_pct: float,
) -> ClosedTrade:
    """Compute a ClosedTrade from an open position and exit parameters."""
    if pos.side == "long":
        actual_exit = fill_price * (1 - slippage_pct)
        pnl = pos.shares * (actual_exit - pos.entry_price) - 2 * commission
    else:
        actual_exit = fill_price * (1 + slippage_pct)
        pnl = pos.shares * (pos.entry_price - actual_exit) - 2 * commission

    cost_basis = pos.shares * pos.entry_price
    pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

    return ClosedTrade(
        symbol=pos.symbol,
        side=pos.side,
        entry_date=pos.entry_date,
        entry_price=pos.entry_price,
        exit_date=exit_date,
        exit_price=actual_exit,
        shares=pos.shares,
        initial_stop=pos.stop_price,
        pnl=round(pnl, 4),
        pnl_pct=round(pnl_pct, 4),
        exit_reason=reason,
    )


def _close_pos(
    sym: str,
    fill_price: float,
    exit_date: str,
    reason: str,
    open_pos: dict[str, _Position],
    closed_trades: list[ClosedTrade],
    commission: float,
    slippage_pct: float,
    cash: float,
) -> float:
    """Remove position from open_pos, record trade, update and return cash."""
    pos = open_pos.pop(sym)
    trade = _make_trade(pos, fill_price, exit_date, reason, commission, slippage_pct)
    closed_trades.append(trade)

    # Update cash
    if pos.side == "long":
        cash += pos.shares * trade.exit_price - commission
    else:
        cash -= pos.shares * trade.exit_price + commission

    logger.debug(
        "[%s] %s exit %.2f pnl=%.2f (%s)",
        sym, pos.side, trade.exit_price, trade.pnl, reason,
    )
    return cash


def _account_value(
    cash: float,
    open_pos: dict[str, _Position],
    sym_data: dict[str, _SymbolData],
    today: date,
) -> float:
    """Mark-to-market account value using today's close for open positions."""
    total = cash
    for sym, pos in open_pos.items():
        if sym in sym_data and today in sym_data[sym].bars:
            close = sym_data[sym].bars[today]["close"]
        else:
            close = pos.entry_price  # fallback: no data today

        if pos.side == "long":
            total += pos.shares * close
        else:
            # Short: we received entry_price * shares in cash, owe close * shares
            total -= pos.shares * close
    return total

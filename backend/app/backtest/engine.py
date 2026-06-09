"""Walk-forward portfolio backtest engine (long-only).

Critical invariant (no look-ahead):
  Signal at bar T is computed from data[0..T] only.
  Entry fills at bar T+1's open price.
  Stop and signal exits also fill at the next bar's open or at the stop price intrabar.

The strategy is the long-only Hidden-Divergence Confluence engine: a BUY enters the
underlying stock at the next open; a SELL (or ATR stop) exits it. Entry candidates are
ranked each day by their confluence ``composite`` (entry score), highest first.

Price basis: yfinance adjusted prices (total-return, dividends included), so strategy and
benchmark returns are comparable.

Survivorship bias limitation:
  If the supplied symbol list is the CURRENT index membership, companies delisted or
  removed during the backtest period are absent. This inflates results. See
  SURVIVORSHIP_BIAS_NOTE below.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Literal

import pandas as pd

from backend.app.config import AppConfig, BacktestConfig
from backend.app.indicators.atr import compute_atr
from backend.app.scoring.confluence import run_engine as _compute_signals

logger = logging.getLogger(__name__)

SURVIVORSHIP_BIAS_NOTE = (
    "SURVIVORSHIP BIAS WARNING: The universe list reflects CURRENT index membership. "
    "Companies delisted, acquired, or removed during the backtest period are absent. "
    "This inflates all performance metrics — treat them as an upper bound."
)

DataFetcher = Callable[[str, date, date], pd.DataFrame]

_MIN_BARS = 50   # minimum bars before a symbol is included in a backtest


# ── Public data structures ─────────────────────────────────────────────────────

@dataclass
class ClosedTrade:
    symbol: str
    side: str               # always "long"
    entry_date: str         # ISO YYYY-MM-DD
    entry_price: float
    exit_date: str
    exit_price: float
    shares: float
    initial_stop: float
    pnl: float              # net P&L after both fees
    pnl_pct: float          # pnl / (entry_price * shares)
    exit_reason: str        # "stop" | "signal" | "end_of_data"
    entry_fee: float = 0.0
    exit_fee: float = 0.0


@dataclass
class BacktestResult:
    metrics: dict
    trades: list[ClosedTrade]
    equity_curve: list[dict]            # [{"date", "equity", "n_open"}, ...]
    params: dict
    strategy: str = "hidden_div"
    survivorship_note: str = field(default=SURVIVORSHIP_BIAS_NOTE)
    benchmark_metrics: dict = field(default_factory=dict)
    benchmark_equity_curve: list[dict] = field(default_factory=list)
    comparison: dict = field(default_factory=dict)
    constraint_counts: dict = field(default_factory=dict)
    # Retained for response-shape compatibility; always None under the long-only engine.
    coverage_report: object | None = None


# ── Internal data structures ───────────────────────────────────────────────────

@dataclass
class _SymbolData:
    dates: list[date]
    bars: dict[date, dict]      # date → {open, high, low, close}
    signals: dict[date, dict]   # date → run_engine output row (includes "composite")
    atr: dict[date, float]


@dataclass
class _Position:
    symbol: str
    side: str
    entry_date: str
    entry_price: float
    shares: float
    stop_price: float
    entry_fee: float = 0.0


@dataclass
class _PendingEntry:
    side: str
    atr_at_signal: float
    signal_date: str
    composite: float = 0.0


# ── Fee formula ────────────────────────────────────────────────────────────────

def _compute_fee(shares: float, fill_price: float, bk: BacktestConfig) -> float:
    """clamp(shares × fee_per_share, fee_min, fee_max_pct × shares × fill_price)."""
    raw = shares * bk.fee_per_share
    cap = bk.fee_max_pct_of_trade * shares * fill_price
    return max(bk.fee_min, min(raw, cap))


def _target_dollars(equity: float, bk: BacktestConfig) -> float:
    """Fixed-fractional target: max(position_size_pct × equity, position_size_min)."""
    return max(bk.position_size_pct * equity, bk.position_size_min)


# ── Engine entry point ─────────────────────────────────────────────────────────

ProgressCallback = Callable[[int, int, str], None]


def run_backtest(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    strategy: Literal["hidden_div"] = "hidden_div",
    # Legacy params (still accepted for backward compat)
    initial_account: float | None = None,
    slippage_pct: float | None = None,
    commission: float | None = None,
    # Portfolio params (all override config defaults when provided)
    initial_fund: float | None = None,
    fee_per_share: float | None = None,
    fee_min: float | None = None,
    fee_max_pct_of_trade: float | None = None,
    position_size_pct: float | None = None,
    position_size_min: float | None = None,
    atr_stop_multiple: float | None = None,
    atr_period: int | None = None,
    max_concurrent_positions: int | None = None,
    per_name_cap_pct: float | None = None,
    top_n: int | None = None,
    benchmark_symbol: str | None = None,
    risk_free_rate: float | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BacktestResult:
    """Run a portfolio-level walk-forward backtest (long-only).

    All portfolio params fall back to config.yaml [backtest] section defaults.
    Legacy initial_account / commission params are mapped to the new model.
    """
    overrides: dict = {}
    if initial_fund is not None:
        overrides["initial_fund"] = initial_fund
    elif initial_account is not None:
        overrides["initial_fund"] = initial_account
    if slippage_pct is not None:
        overrides["slippage_pct"] = slippage_pct
    if fee_per_share is not None:
        overrides["fee_per_share"] = fee_per_share
    if fee_min is not None:
        overrides["fee_min"] = fee_min
    if fee_max_pct_of_trade is not None:
        overrides["fee_max_pct_of_trade"] = fee_max_pct_of_trade
    if position_size_pct is not None:
        overrides["position_size_pct"] = position_size_pct
    if position_size_min is not None:
        overrides["position_size_min"] = position_size_min
    if atr_stop_multiple is not None:
        overrides["atr_stop_multiple"] = atr_stop_multiple
    if atr_period is not None:
        overrides["atr_period"] = atr_period
    if max_concurrent_positions is not None:
        overrides["max_concurrent_positions"] = max_concurrent_positions
    if per_name_cap_pct is not None:
        overrides["per_name_cap_pct"] = per_name_cap_pct
    if top_n is not None:
        overrides["top_n"] = top_n
    if benchmark_symbol is not None:
        overrides["benchmark_symbol"] = benchmark_symbol
    if risk_free_rate is not None:
        overrides["risk_free_rate"] = risk_free_rate

    bk = cfg.backtest.model_copy(update=overrides) if overrides else cfg.backtest

    return _run_long_backtest(
        symbols=symbols, start=start, end=end,
        cfg=cfg, bk=bk, data_fetcher=data_fetcher,
        progress_callback=progress_callback,
    )


# ── LONG backtest ──────────────────────────────────────────────────────────────

def _run_long_backtest(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    bk: BacktestConfig,
    data_fetcher: DataFetcher,
    progress_callback: ProgressCallback | None = None,
) -> BacktestResult:
    sym_data: dict[str, _SymbolData] = {}
    n_syms = len(symbols)
    for i, sym in enumerate(symbols):
        if progress_callback:
            progress_callback(i, n_syms, sym)
        sd = _load_symbol(sym, start, end, cfg, bk, data_fetcher)
        if sd is not None:
            sym_data[sym] = sd
    if progress_callback:
        progress_callback(n_syms, n_syms, "Simulating")

    if not sym_data:
        logger.error("No symbols loaded — aborting backtest")
        return BacktestResult({}, [], [], {"error": "no symbols loaded"}, strategy="hidden_div")

    all_dates: list[date] = sorted({d for sd in sym_data.values() for d in sd.dates})

    closed_trades, equity_curve, constraint_counts = _walk_dates(
        all_dates=all_dates, sym_data=sym_data, cfg=cfg, bk=bk,
    )

    benchmark_metrics, benchmark_eq = _run_benchmark(data_fetcher, start, end, bk)

    from backend.app.backtest.metrics import compute_strategy_metrics, build_comparison
    metrics = compute_strategy_metrics(closed_trades, equity_curve, bk.initial_fund, bk.risk_free_rate)
    comparison = build_comparison(metrics, benchmark_metrics, bk)

    params = _build_params("hidden_div", start, end, symbols, sym_data, bk)

    logger.info(
        "Backtest complete: %d trades, Sharpe=%.2f, maxDD=%.1f%%, CAGR=%.1f%%",
        metrics.get("n_trades", 0), metrics.get("sharpe_ratio", 0.0),
        metrics.get("max_drawdown", 0.0), metrics.get("cagr", 0.0),
    )
    return BacktestResult(
        metrics=metrics, trades=closed_trades, equity_curve=equity_curve,
        params=params, strategy="hidden_div",
        benchmark_metrics=benchmark_metrics, benchmark_equity_curve=benchmark_eq,
        comparison=comparison, constraint_counts=constraint_counts,
    )


# ── Benchmark ─────────────────────────────────────────────────────────────────

def _run_benchmark(
    data_fetcher: DataFetcher,
    start: date,
    end: date,
    bk: BacktestConfig,
) -> tuple[dict, list[dict]]:
    """Buy benchmark_symbol at first available open; hold to end. One entry fee, no exit fee.

    Prices are adjusted / total-return (dividends included) via yfinance auto_adjust=True.
    """
    try:
        df = data_fetcher(bk.benchmark_symbol, start, end)
    except Exception as exc:
        logger.warning("Benchmark fetch failed (%s): %s", bk.benchmark_symbol, exc)
        return {}, []

    if df.empty or len(df) < 2:
        logger.warning("Benchmark %s has insufficient data", bk.benchmark_symbol)
        return {}, []

    dates = [idx.date() if hasattr(idx, "date") else idx for idx in df.index]
    opens = [float(df.iloc[i]["open"]) for i in range(len(df))]
    closes = [float(df.iloc[i]["close"]) for i in range(len(df))]

    entry_price = opens[0] * (1 + bk.slippage_pct)
    entry_fee = _compute_fee(bk.initial_fund / entry_price, entry_price, bk)
    shares = (bk.initial_fund - entry_fee) / entry_price

    equity_curve = [
        {"date": str(d), "equity": round(shares * closes[i], 2), "n_open": 1}
        for i, d in enumerate(dates)
    ]

    from backend.app.backtest.metrics import compute_benchmark_metrics
    bm_metrics = compute_benchmark_metrics(equity_curve, bk.initial_fund, bk.risk_free_rate)
    return bm_metrics, equity_curve


# ── LONG walk ─────────────────────────────────────────────────────────────────

def _walk_dates(
    all_dates: list[date],
    sym_data: dict[str, _SymbolData],
    cfg: AppConfig,
    bk: BacktestConfig,
) -> tuple[list[ClosedTrade], list[dict], dict]:
    """Day-by-day portfolio simulation (long-only).

    Returns: (closed_trades, equity_curve, constraint_counts)
    constraint_counts keys: skipped_no_slot, skipped_no_capital, skipped_top_n
    """
    cash = float(bk.initial_fund)
    open_pos: dict[str, _Position] = {}
    pending_entries: dict[str, _PendingEntry] = {}
    pending_exits: set[str] = set()
    cooldowns: dict[str, int] = {}
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[dict] = []
    cc = {"skipped_no_slot": 0, "skipped_no_capital": 0, "skipped_top_n": 0}

    for day_idx, today in enumerate(all_dates):

        # a. Fill pending signal-exits at today's open
        for sym in list(pending_exits):
            if sym in open_pos and sym in sym_data and today in sym_data[sym].bars:
                bar = sym_data[sym].bars[today]
                cash = _close_pos(
                    sym, bar["open"], str(today), "signal",
                    open_pos, closed_trades, bk.slippage_pct, cash, bk,
                )
        pending_exits.clear()

        # b. Fill pending entries at today's open
        for sym in list(pending_entries.keys()):
            pe = pending_entries[sym]
            if sym not in sym_data or today not in sym_data[sym].bars:
                del pending_entries[sym]
                continue
            bar = sym_data[sym].bars[today]

            entry_p = bar["open"] * (1 + bk.slippage_pct)

            equity = _account_value(cash, open_pos, sym_data, today)
            tgt = min(_target_dollars(equity, bk), bk.per_name_cap_pct * equity)

            shares = tgt / entry_p if entry_p > 0 else 0.0
            entry_fee = _compute_fee(shares, entry_p, bk)
            total_cost = shares * entry_p + entry_fee

            if total_cost > cash or shares < 0.01:
                cc["skipped_no_capital"] += 1
                del pending_entries[sym]
                continue

            stop_p = entry_p - bk.atr_stop_multiple * pe.atr_at_signal
            open_pos[sym] = _Position(
                symbol=sym, side="long", entry_date=str(today),
                entry_price=entry_p, shares=shares, stop_price=stop_p,
                entry_fee=entry_fee,
            )
            cash -= total_cost
            logger.debug("[%s] long entry %.4f@%.2f stop=%.2f fee=%.2f",
                         sym, shares, entry_p, stop_p, entry_fee)
            del pending_entries[sym]

        # c. Check intrabar stops
        for sym in list(open_pos.keys()):
            if sym not in sym_data or today not in sym_data[sym].bars:
                continue
            pos = open_pos[sym]
            if pos.entry_date == str(today):
                continue
            bar = sym_data[sym].bars[today]
            stop_hit, fill_p = _check_stop(pos, bar)
            if stop_hit:
                cash = _close_pos(
                    sym, fill_p, str(today), "stop",
                    open_pos, closed_trades, 0.0, cash, bk,
                )
                cooldowns[sym] = cfg.risk.reentry_cooldown_bars

        # d. Signal analysis — exits + ranked entry candidates
        entry_candidates: list[tuple[float, str, _PendingEntry]] = []

        for sym, sd in sym_data.items():
            if today not in sd.signals:
                continue

            sig_result = sd.signals[today]
            signal = sig_result["signal"]
            composite = sig_result.get("composite", 0.0)
            atr_today = sd.atr.get(today, 0.0)

            if sym in open_pos and open_pos[sym].entry_date != str(today):
                if today in sd.bars:
                    _update_trailing_stop(open_pos[sym], sd.bars[today], atr_today, cfg)

            if sym in cooldowns:
                cooldowns[sym] -= 1
                if cooldowns[sym] <= 0:
                    del cooldowns[sym]

            is_buy = signal in ("Buy", "Strong Buy")
            is_sell = signal in ("Sell", "Strong Sell")

            if sym in open_pos:
                pos = open_pos[sym]
                if pos.side == "long" and is_sell:
                    if day_idx + 1 < len(all_dates):
                        pending_exits.add(sym)
                    else:
                        close_p = sd.bars[today]["close"] if today in sd.bars else pos.entry_price
                        cash = _close_pos(
                            sym, close_p, str(today), "signal",
                            open_pos, closed_trades, bk.slippage_pct, cash, bk,
                        )
            elif (
                sym not in pending_entries
                and sym not in cooldowns
                and day_idx + 1 < len(all_dates)
                and is_buy
            ):
                entry_candidates.append((
                    composite, sym,
                    _PendingEntry(side="long", atr_at_signal=atr_today,
                                  signal_date=str(today), composite=composite),
                ))

        # Ranked selection — highest confluence (entry) score first
        if entry_candidates:
            entry_candidates.sort(key=lambda x: x[0], reverse=True)

            cc["skipped_top_n"] += max(0, len(entry_candidates) - bk.top_n)
            to_process = entry_candidates[:bk.top_n]

            n_open_now = len(open_pos)
            new_pending = 0

            for composite, sym, pe in to_process:
                slots_left = bk.max_concurrent_positions - n_open_now - new_pending
                if slots_left <= 0:
                    cc["skipped_no_slot"] += 1
                    continue

                equity = _account_value(cash, open_pos, sym_data, today)
                tgt = _target_dollars(equity, bk)
                if cash < tgt:
                    cc["skipped_no_capital"] += 1
                    continue

                pending_entries[sym] = pe
                new_pending += 1

        # e. End-of-day equity
        acct = _account_value(cash, open_pos, sym_data, today)
        equity_curve.append({"date": str(today), "equity": round(acct, 2), "n_open": len(open_pos)})

    # Close remaining positions at last close
    if all_dates:
        last_date = all_dates[-1]
        for sym in list(open_pos.keys()):
            if sym in sym_data and last_date in sym_data[sym].bars:
                close_p = sym_data[sym].bars[last_date]["close"]
                cash = _close_pos(
                    sym, close_p, str(last_date), "end_of_data",
                    open_pos, closed_trades, bk.slippage_pct, cash, bk,
                )
            else:
                pos = open_pos.pop(sym)
                exit_fee = _compute_fee(pos.shares, pos.entry_price, bk)
                pnl = pos.shares * 0.0 - pos.entry_fee - exit_fee
                closed_trades.append(ClosedTrade(
                    symbol=pos.symbol, side=pos.side,
                    entry_date=pos.entry_date, entry_price=pos.entry_price,
                    exit_date=str(last_date), exit_price=pos.entry_price,
                    shares=pos.shares, initial_stop=pos.stop_price,
                    pnl=round(pnl, 4), pnl_pct=0.0, exit_reason="end_of_data",
                    entry_fee=round(pos.entry_fee, 4), exit_fee=round(exit_fee, 4),
                ))

    return closed_trades, equity_curve, cc


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_symbol(
    sym: str,
    start: date,
    end: date,
    cfg: AppConfig,
    bk: BacktestConfig,
    data_fetcher: DataFetcher,
) -> _SymbolData | None:
    try:
        df = data_fetcher(sym, start, end)
    except Exception as exc:
        logger.warning("[%s] fetch failed: %s — skipping", sym, exc)
        return None

    if len(df) < _MIN_BARS:
        logger.warning("[%s] only %d bars — need ≥ %d, skipping", sym, len(df), _MIN_BARS)
        return None

    signals_list = _compute_signals(df, cfg, strategy="hidden_div")
    atr_s = compute_atr(df, bk.atr_period)

    dates: list[date] = []
    bars: dict[date, dict] = {}
    signals: dict[date, dict] = {}
    atr: dict[date, float] = {}

    for i, (idx, row) in enumerate(df.iterrows()):
        d = idx.date() if hasattr(idx, "date") else idx
        dates.append(d)
        bars[d] = {
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
        }
        signals[d] = signals_list[i]
        atr[d] = float(atr_s.iat[i]) if not pd.isna(atr_s.iat[i]) else 0.0

    return _SymbolData(dates=dates, bars=bars, signals=signals, atr=atr)


def _check_stop(pos: _Position, bar: dict) -> tuple[bool, float]:
    """Return (stop_hit, fill_price) using intrabar high/low (long position)."""
    if bar["open"] <= pos.stop_price:
        return True, bar["open"]
    if bar["low"] <= pos.stop_price:
        return True, pos.stop_price
    return False, 0.0


def _update_trailing_stop(pos: _Position, bar: dict, atr: float, cfg: AppConfig) -> None:
    """Move the stop up (long) using today's close and ATR."""
    if atr <= 0:
        return
    mult = cfg.backtest.atr_stop_multiple
    new_stop = bar["close"] - mult * atr
    if new_stop > pos.stop_price:
        pos.stop_price = new_stop


def _close_pos(
    sym: str,
    fill_price: float,
    exit_date: str,
    reason: str,
    open_pos: dict[str, _Position],
    closed_trades: list[ClosedTrade],
    slippage_pct: float,
    cash: float,
    bk: BacktestConfig,
) -> float:
    """Close a long position: record trade, update cash."""
    pos = open_pos.pop(sym)
    actual_exit = fill_price * (1 - slippage_pct)
    exit_fee = _compute_fee(pos.shares, actual_exit, bk)
    pnl = pos.shares * (actual_exit - pos.entry_price) - pos.entry_fee - exit_fee
    cost_basis = pos.shares * pos.entry_price
    pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

    closed_trades.append(ClosedTrade(
        symbol=pos.symbol, side=pos.side,
        entry_date=pos.entry_date, entry_price=pos.entry_price,
        exit_date=exit_date, exit_price=round(actual_exit, 6),
        shares=pos.shares, initial_stop=pos.stop_price,
        pnl=round(pnl, 4), pnl_pct=round(pnl_pct, 4), exit_reason=reason,
        entry_fee=round(pos.entry_fee, 4), exit_fee=round(exit_fee, 4),
    ))

    cash += pos.shares * actual_exit - exit_fee
    logger.debug("[%s] long exit %.2f pnl=%.2f fee=%.2f (%s)",
                 sym, actual_exit, pnl, exit_fee, reason)
    return cash


def _account_value(
    cash: float,
    open_pos: dict[str, _Position],
    sym_data: dict[str, _SymbolData],
    today: date,
) -> float:
    total = cash
    for sym, pos in open_pos.items():
        if sym in sym_data and today in sym_data[sym].bars:
            close = sym_data[sym].bars[today]["close"]
        else:
            close = pos.entry_price
        total += pos.shares * close
    return total


def _build_params(
    strategy: str,
    start: date,
    end: date,
    symbols: list[str],
    loaded_data: dict,
    bk: BacktestConfig,
) -> dict:
    return {
        "strategy": strategy,
        "start": str(start),
        "end": str(end),
        "symbols": symbols,
        "n_symbols_loaded": len(loaded_data),
        "initial_fund": bk.initial_fund,
        "slippage_pct": bk.slippage_pct,
        "fee_per_share": bk.fee_per_share,
        "fee_min": bk.fee_min,
        "fee_max_pct_of_trade": bk.fee_max_pct_of_trade,
        "position_size_pct": bk.position_size_pct,
        "position_size_min": bk.position_size_min,
        "atr_stop_multiple": bk.atr_stop_multiple,
        "atr_period": bk.atr_period,
        "max_concurrent_positions": bk.max_concurrent_positions,
        "per_name_cap_pct": bk.per_name_cap_pct,
        "top_n": bk.top_n,
        "benchmark_symbol": bk.benchmark_symbol,
        "risk_free_rate": bk.risk_free_rate,
        "price_basis": "adjusted (total-return, dividends included via yfinance auto_adjust)",
    }

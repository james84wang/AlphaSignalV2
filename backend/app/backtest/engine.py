"""Walk-forward backtest engine. Implements spec §6.5 and §7 defaults.

Critical invariant (no look-ahead):
  Signal at bar T is computed from data[0..T] only.
  Entry fills at bar T+1's open price.
  Stop and signal exits also fill at the next bar's open or at the stop price intrabar.

LONG profile:
  Signal and trade are both on the underlying stock. This is the existing behaviour.

SHORT profile:
  Signal is computed on the underlying stock using the SHORT profile.
  The TRADE is on the ACTUAL inverse ETF (bought at its T+1 open).
  Stop (1.5×ATR) and 2% position sizing are based on the inverse ETF's own ATR.
  P&L is measured on the inverse ETF's real price series.
  Why: inverse ETFs reset daily; multi-day returns diverge from −1× the underlying.
  Testing on the real ETF captures this decay/tracking error honestly.

Survivorship bias limitation:
  If the supplied symbol list is the CURRENT S&P 500 membership, companies that were
  delisted or removed during the backtest period are absent. This inflates results.
  See SURVIVORSHIP_BIAS_NOTE below.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from backend.app.backtest.coverage import (
    CoverageReport,
    SkippedDataError,
    SkippedInsufficientHistory,
    TestedEntry,
)
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

_MIN_BARS = 50   # minimum bars before a symbol is included in a backtest


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
    # Short-only fields (None for long trades)
    underlying_symbol: str | None = None
    trade_instrument: str | None = None      # the actual instrument traded (ETF for short)
    synthetic_pnl: float | None = None       # −1× underlying return over same dates (decay diagnostic)
    synthetic_pnl_pct: float | None = None


@dataclass
class BacktestResult:
    metrics: dict
    trades: list[ClosedTrade]
    equity_curve: list[dict]    # [{"date", "equity", "n_open"}, ...]
    params: dict
    strategy: str = "long"
    survivorship_note: str = field(default=SURVIVORSHIP_BIAS_NOTE)
    coverage_report: CoverageReport | None = None


# ── Internal data structures ───────────────────────────────────────────────────

@dataclass
class _SymbolData:
    """Data for the LONG path: signals and trade bars are both the underlying."""
    dates: list[date]
    bars: dict[date, dict]      # date → {open, high, low, close}
    signals: dict[date, dict]   # date → run_engine output row
    atr: dict[date, float]      # date → ATR value


@dataclass
class _ShortSymbolData:
    """Data for the SHORT path: signals on underlying, trades on inverse ETF."""
    underlying: str
    etf_symbol: str
    # Signal source: underlying with short profile
    signal_dates: list[date]
    signals: dict[date, dict]   # date → run_engine output row (underlying)
    underlying_bars: dict[date, dict]   # underlying OHLCV for synthetic return calc
    # Trade source: inverse ETF
    etf_dates: list[date]
    etf_bars: dict[date, dict]  # date → {open, high, low, close} of the ETF
    etf_atr: dict[date, float]  # date → ATR computed on the ETF
    # Window where both series overlap
    overlap_dates: list[date]
    skipped_before_overlap: int  # signals before ETF launch that were skipped


@dataclass
class _Position:
    symbol: str
    side: str
    entry_date: str
    entry_price: float
    shares: float
    stop_price: float
    # For SHORT trades: track the underlying symbol and the ETF entry price reference
    underlying_symbol: str | None = None
    trade_instrument: str | None = None
    underlying_entry_close: float | None = None  # underlying close on entry bar (for synthetic calc)


@dataclass
class _PendingEntry:
    side: str
    atr_at_signal: float
    signal_date: str
    # Short-specific: the instrument to actually trade
    trade_instrument: str | None = None
    underlying_symbol: str | None = None
    underlying_bar_close: float | None = None  # underlying close on signal bar


# ── Engine ─────────────────────────────────────────────────────────────────────

ProgressCallback = Callable[[int, int, str], None]


def run_backtest(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    strategy: Literal["long", "short"] = "long",
    initial_account: float | None = None,
    slippage_pct: float | None = None,
    commission: float | None = None,
    inverse_etf_map: dict[str, str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BacktestResult:
    """Run a walk-forward backtest over *symbols* from *start* to *end*.

    Args:
        symbols: ticker list (e.g. ["AAPL", "MSFT"])
        start:   backtest start date (inclusive)
        end:     backtest end date (inclusive)
        cfg:     loaded AppConfig (weights, risk rules, etc.)
        data_fetcher: callable(symbol, start, end) → OHLCV DataFrame
        strategy: "long" (trade underlying) or "short" (signal on underlying, trade ETF)
        initial_account: starting portfolio value in USD
        slippage_pct: fraction of fill price lost to slippage (both entry and exit)
        commission:   flat dollar commission per fill
        inverse_etf_map: {underlying → inverse_etf_symbol}. Required for strategy="short".
                         If None, attempts to load from data/inverse_etfs.csv.

    Returns:
        BacktestResult with metrics, trade log, equity curve, params, and (for short
        runs) a CoverageReport.
    """
    if initial_account is None:
        initial_account = cfg.backtest.initial_account
    if slippage_pct is None:
        slippage_pct = cfg.backtest.slippage_pct
    if commission is None:
        commission = cfg.backtest.commission_per_trade

    if strategy == "short":
        return _run_short_backtest(
            symbols=symbols,
            start=start,
            end=end,
            cfg=cfg,
            data_fetcher=data_fetcher,
            initial_account=initial_account,
            slippage_pct=slippage_pct,
            commission=commission,
            inverse_etf_map=inverse_etf_map or _load_default_etf_map(),
            progress_callback=progress_callback,
        )

    return _run_long_backtest(
        symbols=symbols,
        start=start,
        end=end,
        cfg=cfg,
        data_fetcher=data_fetcher,
        initial_account=initial_account,
        slippage_pct=slippage_pct,
        commission=commission,
        progress_callback=progress_callback,
    )


# ── LONG backtest (existing behaviour, now explicit) ───────────────────────────

def _run_long_backtest(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    initial_account: float,
    slippage_pct: float,
    commission: float,
    progress_callback: ProgressCallback | None = None,
) -> BacktestResult:
    # ── 1. Load and pre-compute per-symbol data ────────────────────────────────
    sym_data: dict[str, _SymbolData] = {}
    n_syms = len(symbols)
    for i, sym in enumerate(symbols):
        if progress_callback:
            progress_callback(i, n_syms, sym)
        sd = _load_symbol(sym, start, end, cfg, data_fetcher, strategy="long")
        if sd is not None:
            sym_data[sym] = sd
    if progress_callback:
        progress_callback(n_syms, n_syms, "Simulating")

    if not sym_data:
        logger.error("No symbols loaded — aborting long backtest")
        return BacktestResult({}, [], [], {"error": "no symbols loaded"}, strategy="long")

    all_dates: list[date] = sorted({d for sd in sym_data.values() for d in sd.dates})

    closed_trades, equity_curve = _walk_dates(
        all_dates=all_dates,
        sym_data=sym_data,
        cfg=cfg,
        initial_account=initial_account,
        slippage_pct=slippage_pct,
        commission=commission,
        strategy="long",
    )

    from backend.app.backtest.metrics import compute_metrics
    metrics = compute_metrics(closed_trades, equity_curve, initial_account)

    params = {
        "strategy": "long",
        "start": str(start),
        "end": str(end),
        "symbols": symbols,
        "n_symbols_loaded": len(sym_data),
        "initial_account": initial_account,
        "slippage_pct": slippage_pct,
        "commission": commission,
    }

    logger.info(
        "Long backtest complete: %d trades, Sharpe=%.2f, maxDD=%.1f%%, CAGR=%.1f%%",
        metrics.get("n_trades", 0),
        metrics.get("sharpe", 0.0),
        metrics.get("max_drawdown_pct", 0.0),
        metrics.get("cagr", 0.0),
    )
    return BacktestResult(
        metrics=metrics,
        trades=closed_trades,
        equity_curve=equity_curve,
        params=params,
        strategy="long",
    )


# ── SHORT backtest ─────────────────────────────────────────────────────────────

def _run_short_backtest(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    initial_account: float,
    slippage_pct: float,
    commission: float,
    inverse_etf_map: dict[str, str],
    progress_callback: ProgressCallback | None = None,
) -> BacktestResult:
    coverage = CoverageReport()

    # ── 1. Classify and load each underlying ──────────────────────────────────
    short_data: dict[str, _ShortSymbolData] = {}
    n_syms = len(symbols)

    for i, sym in enumerate(symbols):
        if progress_callback:
            progress_callback(i, n_syms, sym)
        if sym not in inverse_etf_map:
            coverage.skipped_no_instrument.append(sym)
            continue

        etf_sym = inverse_etf_map[sym]

        # Load underlying (for signals)
        try:
            underlying_df = data_fetcher(sym, start, end)
        except Exception as exc:
            coverage.skipped_data_error.append(SkippedDataError(sym, f"underlying fetch: {exc}"))
            continue

        if len(underlying_df) < _MIN_BARS:
            coverage.skipped_data_error.append(
                SkippedDataError(sym, f"underlying has only {len(underlying_df)} bars (need ≥ {_MIN_BARS})")
            )
            continue

        # Load inverse ETF (for trade fills)
        try:
            etf_df = data_fetcher(etf_sym, start, end)
        except Exception as exc:
            coverage.skipped_data_error.append(
                SkippedDataError(etf_sym, f"ETF fetch for {sym}: {exc}")
            )
            continue

        # Compute overlap between underlying and ETF
        underlying_dates = set(
            idx.date() if hasattr(idx, "date") else idx
            for idx in underlying_df.index
        )
        etf_dates_set = set(
            idx.date() if hasattr(idx, "date") else idx
            for idx in etf_df.index
        )
        overlap = sorted(underlying_dates & etf_dates_set)

        if len(overlap) < _MIN_BARS:
            coverage.skipped_insufficient_history.append(
                SkippedInsufficientHistory(
                    underlying=sym,
                    inverse_etf=etf_sym,
                    reason=f"only {len(overlap)} overlapping bars (need ≥ {_MIN_BARS})",
                )
            )
            continue

        # Pre-compute signals on underlying with SHORT profile
        signals_list = _compute_signals(underlying_df, cfg, strategy="short")
        underlying_bars: dict[date, dict] = {}
        signals_dict: dict[date, dict] = {}
        signal_dates: list[date] = []

        for i, (idx, row) in enumerate(underlying_df.iterrows()):
            d = idx.date() if hasattr(idx, "date") else idx
            signal_dates.append(d)
            underlying_bars[d] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            signals_dict[d] = signals_list[i]

        # Pre-compute ETF bars and ATR
        etf_atr_s = compute_atr(etf_df, cfg.risk.stop_loss_atr_period)
        etf_bars: dict[date, dict] = {}
        etf_atr: dict[date, float] = {}
        etf_date_list: list[date] = []

        for i, (idx, row) in enumerate(etf_df.iterrows()):
            d = idx.date() if hasattr(idx, "date") else idx
            etf_date_list.append(d)
            etf_bars[d] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            etf_atr[d] = float(etf_atr_s.iat[i]) if not pd.isna(etf_atr_s.iat[i]) else 0.0

        # Count signals that fired before the ETF launched (before overlap starts)
        etf_first_date = overlap[0]
        skipped_before = sum(
            1 for d in signal_dates
            if d < etf_first_date
            and signals_dict[d]["signal"] in ("Sell", "Strong Sell")
        )

        short_data[sym] = _ShortSymbolData(
            underlying=sym,
            etf_symbol=etf_sym,
            signal_dates=signal_dates,
            signals=signals_dict,
            underlying_bars=underlying_bars,
            etf_dates=etf_date_list,
            etf_bars=etf_bars,
            etf_atr=etf_atr,
            overlap_dates=overlap,
            skipped_before_overlap=skipped_before,
        )

    if progress_callback:
        progress_callback(n_syms, n_syms, "Simulating")

    if not short_data:
        logger.warning("No short-side symbols are testable — returning coverage report only")
        coverage.print_human_readable()
        empty_params = {
            "strategy": "short",
            "start": str(start),
            "end": str(end),
            "symbols": symbols,
            "n_symbols_loaded": 0,
            "initial_account": initial_account,
        }
        return BacktestResult({}, [], [], empty_params, strategy="short", coverage_report=coverage)

    # ── 2. Walk the shared calendar ────────────────────────────────────────────
    all_dates: list[date] = sorted(
        {d for sd in short_data.values() for d in sd.overlap_dates}
    )

    cash = float(initial_account)
    open_pos: dict[str, _Position] = {}
    pending_entries: dict[str, _PendingEntry] = {}
    pending_exits: set[str] = set()
    cooldowns: dict[str, int] = {}
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[dict] = []

    for day_idx, today in enumerate(all_dates):

        # a. Fill pending signal-exits (short trade: sell the ETF) at today's open
        for sym in list(pending_exits):
            if sym in open_pos:
                pos = open_pos[sym]
                etf_sym = pos.trade_instrument
                if etf_sym and etf_sym in _etf_sym_to_sdata(short_data):
                    sd = _etf_sym_to_sdata(short_data)[etf_sym]
                    if today in sd.etf_bars:
                        bar = sd.etf_bars[today]
                        synthetic_pnl, synthetic_pnl_pct = _compute_synthetic(
                            pos, today, sd.underlying_bars
                        )
                        cash = _close_short_pos(
                            sym, bar["open"], str(today), "signal",
                            open_pos, closed_trades, commission, slippage_pct, cash,
                            synthetic_pnl=synthetic_pnl,
                            synthetic_pnl_pct=synthetic_pnl_pct,
                        )
        pending_exits.clear()

        # b. Fill pending entries (buy the inverse ETF at its open)
        for sym in list(pending_entries.keys()):
            pe = pending_entries[sym]
            if sym not in short_data:
                del pending_entries[sym]
                continue
            sd = short_data[sym]
            etf_sym = pe.trade_instrument
            if today not in sd.etf_bars:
                del pending_entries[sym]
                continue

            bar = sd.etf_bars[today]
            acct = _account_value_short(cash, open_pos, short_data, today)
            # slippage on the ETF (buying the inverse ETF)
            entry_p = bar["open"] * (1 + slippage_pct)

            # Risk sizing on the ETF's own ATR
            etf_atr_today = sd.etf_atr.get(today, 0.0)
            risk_per_share = cfg.risk.stop_loss_atr_mult * etf_atr_today
            if risk_per_share > 0:
                shares = (acct * cfg.risk.position_size_pct) / risk_per_share
                max_shares = max(0.0, (cash - commission) / entry_p) if entry_p > 0 else 0.0
                shares = min(shares, max_shares)

                if shares > 0.01:
                    stop_p = entry_p - cfg.risk.stop_loss_atr_mult * etf_atr_today
                    open_pos[sym] = _Position(
                        symbol=sym,
                        side="short",   # logical side (underlying short)
                        entry_date=str(today),
                        entry_price=entry_p,
                        shares=shares,
                        stop_price=stop_p,
                        underlying_symbol=sym,
                        trade_instrument=etf_sym,
                        underlying_entry_close=pe.underlying_bar_close,
                    )
                    cash -= shares * entry_p + commission
                    logger.debug(
                        "[%s→%s] short entry %.4f shares @ %.2f stop=%.2f",
                        sym, etf_sym, shares, entry_p, stop_p,
                    )
            del pending_entries[sym]

        # c. Check intrabar stops (on the ETF's high/low)
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            if sym not in short_data:
                continue
            sd = short_data[sym]
            etf_sym = pos.trade_instrument
            if today not in sd.etf_bars:
                continue
            if pos.entry_date == str(today):
                continue
            bar = sd.etf_bars[today]
            # We hold the ETF long (bought it) — stop is below entry
            stop_hit, fill_p = _check_etf_long_stop(pos, bar)
            if stop_hit:
                synthetic_pnl, synthetic_pnl_pct = _compute_synthetic(pos, today, sd.underlying_bars)
                cash = _close_short_pos(
                    sym, fill_p, str(today), "stop",
                    open_pos, closed_trades, commission, 0.0, cash,
                    synthetic_pnl=synthetic_pnl,
                    synthetic_pnl_pct=synthetic_pnl_pct,
                )
                cooldowns[sym] = cfg.risk.reentry_cooldown_bars

        # d. Signal analysis
        n_open = len(open_pos)
        for sym, sd in short_data.items():
            if today not in sd.signals:
                continue
            if today not in sd.etf_bars:
                continue  # can only trade if ETF data also exists today

            sig_result = sd.signals[today]
            signal = sig_result["signal"]
            etf_atr_today = sd.etf_atr.get(today, 0.0)

            # Update trailing stop on open ETF position
            if sym in open_pos and open_pos[sym].entry_date != str(today):
                if today in sd.etf_bars:
                    _update_etf_trailing_stop(open_pos[sym], sd.etf_bars[today], etf_atr_today, cfg)

            if sym in cooldowns:
                cooldowns[sym] -= 1
                if cooldowns[sym] <= 0:
                    del cooldowns[sym]

            is_sell = signal in ("Sell", "Strong Sell")
            is_buy = signal in ("Buy", "Strong Buy")   # exit signal for short

            # Exit existing ETF position on opposite signal (buy signal = exit short)
            if sym in open_pos:
                if is_buy and day_idx + 1 < len(all_dates):
                    pending_exits.add(sym)
                elif is_buy:
                    if today in sd.etf_bars:
                        bar = sd.etf_bars[today]
                        synthetic_pnl, synthetic_pnl_pct = _compute_synthetic(
                            open_pos[sym], today, sd.underlying_bars
                        )
                        cash = _close_short_pos(
                            sym, bar["close"], str(today), "signal",
                            open_pos, closed_trades, commission, slippage_pct, cash,
                            synthetic_pnl=synthetic_pnl,
                            synthetic_pnl_pct=synthetic_pnl_pct,
                        )

            elif (
                is_sell
                and sym not in pending_entries
                and sym not in cooldowns
                and n_open + len(pending_entries) < cfg.risk.max_concurrent_positions
                and day_idx + 1 < len(all_dates)
                # next day must have ETF data
                and all_dates[day_idx + 1] in sd.etf_bars
            ):
                underlying_close = sd.underlying_bars[today]["close"] if today in sd.underlying_bars else None
                pending_entries[sym] = _PendingEntry(
                    side="short",
                    atr_at_signal=etf_atr_today,
                    signal_date=str(today),
                    trade_instrument=sd.etf_symbol,
                    underlying_symbol=sym,
                    underlying_bar_close=underlying_close,
                )

        # e. Record end-of-day equity
        acct = _account_value_short(cash, open_pos, short_data, today)
        equity_curve.append({"date": str(today), "equity": round(acct, 2), "n_open": len(open_pos)})

    # ── 3. Close all remaining ETF positions at last close ─────────────────────
    if all_dates:
        last_date = all_dates[-1]
        for sym in list(open_pos.keys()):
            pos = open_pos[sym]
            sd = short_data.get(sym)
            if sd and last_date in sd.etf_bars:
                close_p = sd.etf_bars[last_date]["close"]
            else:
                close_p = pos.entry_price
            synthetic_pnl, synthetic_pnl_pct = _compute_synthetic(
                pos, last_date, sd.underlying_bars if sd else {}
            )
            cash = _close_short_pos(
                sym, close_p, str(last_date), "end_of_data",
                open_pos, closed_trades, commission, slippage_pct, cash,
                synthetic_pnl=synthetic_pnl,
                synthetic_pnl_pct=synthetic_pnl_pct,
            )

    # ── 4. Build coverage report entries ──────────────────────────────────────
    for sym, sd in short_data.items():
        n_trades = sum(1 for t in closed_trades if t.underlying_symbol == sym)
        coverage.tested.append(TestedEntry(
            underlying=sym,
            inverse_etf=sd.etf_symbol,
            window_tested_start=str(sd.overlap_dates[0]) if sd.overlap_dates else "",
            window_tested_end=str(sd.overlap_dates[-1]) if sd.overlap_dates else "",
            n_trades=n_trades,
            skipped_signals_before_etf_launch=sd.skipped_before_overlap,
        ))

    coverage.print_human_readable()

    from backend.app.backtest.metrics import compute_metrics
    metrics = compute_metrics(closed_trades, equity_curve, initial_account)

    params = {
        "strategy": "short",
        "start": str(start),
        "end": str(end),
        "symbols": symbols,
        "n_symbols_loaded": len(short_data),
        "initial_account": initial_account,
        "slippage_pct": slippage_pct,
        "commission": commission,
        "caveats": [
            "Single-stock inverse ETFs are recent — short-side history may be < 3 years for most names.",
            "Thin inverse ETFs have wider spreads; the default slippage may be optimistic.",
            "Survivorship bias: current-membership universe only.",
        ],
    }

    logger.info(
        "Short backtest complete: %d trades across %d names, Sharpe=%.2f, maxDD=%.1f%%",
        metrics.get("n_trades", 0),
        len(short_data),
        metrics.get("sharpe", 0.0),
        metrics.get("max_drawdown_pct", 0.0),
    )
    return BacktestResult(
        metrics=metrics,
        trades=closed_trades,
        equity_curve=equity_curve,
        params=params,
        strategy="short",
        coverage_report=coverage,
    )


# ── LONG path helpers ──────────────────────────────────────────────────────────

def _load_symbol(
    sym: str,
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    strategy: Literal["long", "short"] = "long",
) -> _SymbolData | None:
    """Fetch OHLCV data and pre-compute signals + ATR for one symbol."""
    try:
        df = data_fetcher(sym, start, end)
    except Exception as exc:
        logger.warning("[%s] fetch failed: %s — skipping", sym, exc)
        return None

    if len(df) < _MIN_BARS:
        logger.warning("[%s] only %d bars — need ≥ %d, skipping", sym, len(df), _MIN_BARS)
        return None

    signals_list = _compute_signals(df, cfg, strategy=strategy)
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


def _check_etf_long_stop(pos: _Position, etf_bar: dict) -> tuple[bool, float]:
    """Stop check for the inverse ETF position (held long). Stop is below entry."""
    if etf_bar["open"] <= pos.stop_price:
        return True, etf_bar["open"]
    if etf_bar["low"] <= pos.stop_price:
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


def _update_etf_trailing_stop(pos: _Position, etf_bar: dict, etf_atr: float, cfg: AppConfig) -> None:
    """Trailing stop for an ETF long position: move stop up as ETF price rises."""
    if etf_atr <= 0:
        return
    new_stop = etf_bar["close"] - cfg.risk.trail_stop_atr_mult * etf_atr
    if new_stop > pos.stop_price:
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
        actual_exit = fill_price * (1 - slippage_pct)
        pnl = pos.shares * (actual_exit - pos.entry_price) - 2 * commission

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

    if pos.side == "long":
        cash += pos.shares * trade.exit_price - commission
    else:
        cash -= pos.shares * trade.exit_price + commission

    logger.debug(
        "[%s] %s exit %.2f pnl=%.2f (%s)",
        sym, pos.side, trade.exit_price, trade.pnl, reason,
    )
    return cash


def _close_short_pos(
    sym: str,
    fill_price: float,
    exit_date: str,
    reason: str,
    open_pos: dict[str, _Position],
    closed_trades: list[ClosedTrade],
    commission: float,
    slippage_pct: float,
    cash: float,
    synthetic_pnl: float | None = None,
    synthetic_pnl_pct: float | None = None,
) -> float:
    """Close an ETF long position, record a ClosedTrade, and return updated cash."""
    pos = open_pos.pop(sym)
    actual_exit = fill_price * (1 - slippage_pct)
    pnl = pos.shares * (actual_exit - pos.entry_price) - 2 * commission
    cost_basis = pos.shares * pos.entry_price
    pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

    trade = ClosedTrade(
        symbol=pos.trade_instrument or sym,
        side="short",
        entry_date=pos.entry_date,
        entry_price=pos.entry_price,
        exit_date=exit_date,
        exit_price=round(actual_exit, 6),
        shares=pos.shares,
        initial_stop=pos.stop_price,
        pnl=round(pnl, 4),
        pnl_pct=round(pnl_pct, 4),
        exit_reason=reason,
        underlying_symbol=pos.underlying_symbol,
        trade_instrument=pos.trade_instrument,
        synthetic_pnl=round(synthetic_pnl, 4) if synthetic_pnl is not None else None,
        synthetic_pnl_pct=round(synthetic_pnl_pct, 4) if synthetic_pnl_pct is not None else None,
    )
    closed_trades.append(trade)
    cash += pos.shares * actual_exit - commission
    logger.debug(
        "[%s→%s] ETF exit %.2f pnl=%.2f synth=%.2f (%s)",
        pos.underlying_symbol, pos.trade_instrument, actual_exit,
        trade.pnl, trade.synthetic_pnl or 0.0, reason,
    )
    return cash


def _compute_synthetic(
    pos: _Position,
    exit_date: date,
    underlying_bars: dict[date, dict],
) -> tuple[float | None, float | None]:
    """Compute synthetic P&L by inverting the underlying's return over the trade window.

    This is the 'naive synthetic short' — what we'd compute if we just flipped
    the underlying's return. Comparing this to the real ETF P&L shows decay drag.
    """
    entry_d = date.fromisoformat(pos.entry_date)
    if pos.underlying_entry_close is None:
        return None, None
    if exit_date not in underlying_bars:
        return None, None

    underlying_entry_close = pos.underlying_entry_close
    underlying_exit_close = underlying_bars[exit_date]["close"]

    if underlying_entry_close <= 0:
        return None, None

    # Naive synthetic short return: −1 × underlying return
    underlying_ret = (underlying_exit_close - underlying_entry_close) / underlying_entry_close
    synthetic_ret = -underlying_ret

    # Scale to the same dollar size as the real trade
    cost_basis = pos.shares * pos.entry_price
    synthetic_pnl = cost_basis * synthetic_ret
    synthetic_pnl_pct = synthetic_ret * 100
    return synthetic_pnl, synthetic_pnl_pct


def _etf_sym_to_sdata(short_data: dict[str, "_ShortSymbolData"]) -> dict[str, "_ShortSymbolData"]:
    """Return a dict keyed by ETF symbol instead of underlying symbol."""
    return {sd.etf_symbol: sd for sd in short_data.values()}


def _account_value_short(
    cash: float,
    open_pos: dict[str, _Position],
    short_data: dict[str, "_ShortSymbolData"],
    today: date,
) -> float:
    """Mark-to-market: ETF positions held long (bought)."""
    total = cash
    for sym, pos in open_pos.items():
        sd = short_data.get(sym)
        if sd and today in sd.etf_bars:
            close = sd.etf_bars[today]["close"]
        else:
            close = pos.entry_price
        # We hold the ETF long
        total += pos.shares * close
    return total


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
            close = pos.entry_price
        if pos.side == "long":
            total += pos.shares * close
        else:
            total -= pos.shares * close
    return total


# ── Shared walk-forward loop (LONG only) ──────────────────────────────────────

def _walk_dates(
    all_dates: list[date],
    sym_data: dict[str, _SymbolData],
    cfg: AppConfig,
    initial_account: float,
    slippage_pct: float,
    commission: float,
    strategy: str,
) -> tuple[list[ClosedTrade], list[dict]]:
    """Core day-by-day walk for the LONG path."""
    cash = float(initial_account)
    open_pos: dict[str, _Position] = {}
    pending_entries: dict[str, _PendingEntry] = {}
    pending_exits: set[str] = set()
    cooldowns: dict[str, int] = {}
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[dict] = []

    for day_idx, today in enumerate(all_dates):

        # a. Fill pending signal-exits at today's open
        for sym in list(pending_exits):
            if sym in open_pos and sym in sym_data and today in sym_data[sym].bars:
                bar = sym_data[sym].bars[today]
                cash = _close_pos(
                    sym, bar["open"], str(today), "signal",
                    open_pos, closed_trades, commission, slippage_pct, cash,
                )
        pending_exits.clear()

        # b. Fill pending entries at today's open
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
                if pe.side == "long":
                    max_shares = max(0.0, (cash - commission) / entry_p) if entry_p > 0 else 0.0
                    shares = min(shares, max_shares)
                else:
                    if cash < commission:
                        shares = 0.0

                if shares > 0.01:
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
                    open_pos, closed_trades, commission, 0.0, cash,
                )
                cooldowns[sym] = cfg.risk.reentry_cooldown_bars

        # d. Signal analysis
        n_open = len(open_pos)
        for sym, sd in sym_data.items():
            if today not in sd.signals:
                continue

            sig_result = sd.signals[today]
            signal = sig_result["signal"]
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
                if (pos.side == "long" and is_sell) or (pos.side == "short" and is_buy):
                    if day_idx + 1 < len(all_dates):
                        pending_exits.add(sym)
                    else:
                        close_p = sd.bars[today]["close"] if today in sd.bars else pos.entry_price
                        cash = _close_pos(
                            sym, close_p, str(today), "signal",
                            open_pos, closed_trades, commission, slippage_pct, cash,
                        )
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

        # e. End-of-day equity
        acct = _account_value(cash, open_pos, sym_data, today)
        equity_curve.append({"date": str(today), "equity": round(acct, 2), "n_open": len(open_pos)})

    # ── Close remaining positions ──────────────────────────────────────────────
    if all_dates:
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
                closed_trades.append(
                    _make_trade(pos, pos.entry_price, str(last_date), "end_of_data", commission, slippage_pct)
                )

    return closed_trades, equity_curve


# ── Utility ────────────────────────────────────────────────────────────────────

def _load_default_etf_map() -> dict[str, str]:
    """Load inverse_etfs.csv from the repo data/ directory."""
    csv_path = Path(__file__).resolve().parents[3] / "data" / "inverse_etfs.csv"
    if not csv_path.exists():
        logger.warning("inverse_etfs.csv not found at %s", csv_path)
        return {}
    try:
        import csv
        result: dict[str, str] = {}
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result[row["underlying_symbol"].strip()] = row["inverse_etf_symbol"].strip()
        return result
    except Exception as exc:
        logger.error("Failed to load inverse_etfs.csv: %s", exc)
        return {}

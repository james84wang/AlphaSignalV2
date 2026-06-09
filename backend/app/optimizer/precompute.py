"""Pre-compute confluence events for all symbols, once, over the full date range.

The expensive parts of the strategy — swing pivots, MACD/RSI divergence, DeMark
TD Sequential, the EMA regime gate, and the RSI zone — depend only on the
*structural* parameters, never on the tunable entry/exit weights, thresholds, or
confluence windows. So we compute them once per symbol here, then each optimiser
trial only re-applies the cheap scoring step (:func:`compute_signals`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from backend.app.config import AppConfig
from backend.app.indicators.atr import compute_atr
from backend.app.scoring.confluence import ConfluenceEvents, compute_events

logger = logging.getLogger(__name__)

DataFetcher = Callable[[str, date, date], pd.DataFrame]

_MIN_BARS = 50


@dataclass
class PrecomputedSymbol:
    sym: str
    dates: list[date]                # sorted, all bars in the full range
    bars: dict[date, dict]           # date → {open, high, low, close}
    atr: dict[date, float]           # for ATR stop sizing
    events: ConfluenceEvents         # per-bar event arrays, aligned to `dates`

    _date_to_pos: dict[date, int] = field(default_factory=dict, repr=False)

    def date_pos(self, d: date) -> int | None:
        if not self._date_to_pos:
            self._date_to_pos = {dd: i for i, dd in enumerate(self.dates)}
        return self._date_to_pos.get(d)

    def dates_in_range(self, start: date, end: date) -> list[date]:
        return [d for d in self.dates if start <= d <= end]


def precompute_symbols(
    symbols: list[str],
    start: date,
    end: date,
    cfg: AppConfig,
    data_fetcher: DataFetcher,
    include_scoring_tables: bool = False,  # accepted for signature compat; unused
) -> dict[str, PrecomputedSymbol]:
    """Fetch data and pre-compute confluence events for every symbol."""
    strat = cfg.get_strategy("hidden_div")
    result: dict[str, PrecomputedSymbol] = {}

    for sym in symbols:
        try:
            df = data_fetcher(sym, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] fetch failed: %s — skipping", sym, exc)
            continue
        if len(df) < _MIN_BARS:
            logger.debug("[%s] only %d bars — skipping", sym, len(df))
            continue

        atr_s = compute_atr(df, cfg.backtest.atr_period)
        events = compute_events(df, strat)

        dates: list[date] = [idx.date() if hasattr(idx, "date") else idx for idx in df.index]
        bars: dict[date, dict] = {}
        atr_vals: dict[date, float] = {}
        for i, d in enumerate(dates):
            bars[d] = {
                "open": float(df.iloc[i]["open"]), "high": float(df.iloc[i]["high"]),
                "low": float(df.iloc[i]["low"]), "close": float(df.iloc[i]["close"]),
            }
            atr_vals[d] = float(atr_s.iat[i]) if not pd.isna(atr_s.iat[i]) else 0.0

        result[sym] = PrecomputedSymbol(sym=sym, dates=dates, bars=bars, atr=atr_vals, events=events)

    logger.info("Pre-computed %d of %d symbols", len(result), len(symbols))
    return result

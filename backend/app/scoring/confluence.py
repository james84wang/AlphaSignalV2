"""Hidden-Divergence Confluence engine — the strategy source of truth in code.

Implements ``V2-1/hidden_div_confluence_logic.md``. Long-only, event-driven:

  * **BUY**  fires inside a confirmed uptrend when a hidden-bullish divergence
    (MACD or RSI) prints on the bar AND the weighted *entry* confluence score
    reaches the entry threshold.
  * **SELL** fires (ungated) when a bearish-divergence / DeMark-sell event prints
    AND the weighted *exit* confluence score reaches the (lower) exit threshold.

The per-bar output keeps the contract the rest of the app consumes — ``signal``
(Strong Buy | Buy | Hold | Sell) and ``composite`` (used by the backtest to rank
Top-N entry candidates):

  * BUY  → ``composite = +entry_score`` (0–100; higher = more conviction)
  * SELL → ``composite = -exit_score``
  * Hold → ``composite = 0``

Design split (so the optimiser can reuse this logic without recomputing the
expensive parts each trial):
  * :func:`compute_events` — pivots, divergence, DeMark, regime, RSI zone. These
    depend only on the *structural* parameters, never on the tunable weights /
    thresholds / windows.
  * :func:`compute_signals` — turns events + weights/thresholds/windows into the
    per-bar signal arrays. Cheap; safe to call once per optimiser trial.

No look-ahead: every divergence/DeMark event is detected on *confirmed* bars, so
a signal on bar T uses only data available at the close of bar T (or earlier).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from backend.app.config import AppConfig, EntryConfig, ExitConfig, StrategyConfig
from backend.app.indicators.demark import compute_demark
from backend.app.indicators.divergence import detect_divergences
from backend.app.indicators.ema import compute_emas
from backend.app.indicators.macd import compute_macd
from backend.app.indicators.rsi import compute_rsi
from backend.app.indicators.swing_pivots import find_pivots

ENTRY_COMPONENTS = ("macd_hidden_bull", "rsi_hidden_bull", "rsi_zone", "demark_td9_buy")
EXIT_COMPONENTS = ("demark_td13_sell", "macd_regular_bear", "rsi_regular_bear", "demark_td9_sell")


@dataclass
class ConfluenceEvents:
    """Per-bar boolean event arrays — independent of weights/thresholds/windows."""
    dates: list[str]
    regime_gate: np.ndarray
    rsi_zone: np.ndarray
    macd_hidden_bull: np.ndarray
    rsi_hidden_bull: np.ndarray
    demark_td9_buy: np.ndarray
    demark_td13_sell: np.ndarray
    macd_regular_bear: np.ndarray
    rsi_regular_bear: np.ndarray
    demark_td9_sell: np.ndarray

    @property
    def n(self) -> int:
        return len(self.dates)


@dataclass
class SignalArrays:
    """Per-bar outputs for one (weights/thresholds/windows) configuration."""
    signals: list[str]
    composite: np.ndarray
    entry_score: np.ndarray
    exit_score: np.ndarray
    fired: dict[str, np.ndarray]   # component name → per-bar "counts toward score" bool


# ── Event computation (structural params only) ──────────────────────────────────

def compute_events(df: pd.DataFrame, strat: StrategyConfig) -> ConfluenceEvents:
    """Compute the eight confluence events + regime gate over a daily OHLCV frame."""
    n = len(df)
    dates = [str(idx.date()) if hasattr(idx, "date") else str(idx) for idx in df.index]
    close = df["close"]

    reg = strat.regime
    ema_df = compute_emas(df, [reg.ema_fast, reg.ema_slow], reg.slope_lookback)
    ema_fast = ema_df[f"ema_{reg.ema_fast}"]
    ema_slow = ema_df[f"ema_{reg.ema_slow}"]
    fast_rising = ema_fast > ema_fast.shift(reg.slope_lookback)
    slow_rising = ema_slow > ema_slow.shift(reg.slope_lookback)
    regime_gate = (
        (ema_fast > ema_slow) & fast_rising & slow_rising & (close > ema_slow)
    ).to_numpy()

    macd_line = compute_macd(df, strat.macd.fast, strat.macd.slow, strat.macd.signal)["macd_line"].to_numpy()
    rsi = compute_rsi(df, strat.rsi.period)
    rsi_np = rsi.to_numpy()

    piv = strat.pivots
    pivot_lows, pivot_highs = find_pivots(
        df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float), piv.left, piv.right,
    )
    macd_hidden_bull, macd_regular_bear = detect_divergences(
        macd_line, pivot_lows, pivot_highs, n,
        min_bars=piv.min_bars, max_bars=piv.max_bars, right=piv.right,
    )
    rsi_hidden_bull, rsi_regular_bear = detect_divergences(
        rsi_np, pivot_lows, pivot_highs, n,
        min_bars=piv.min_bars, max_bars=piv.max_bars, right=piv.right,
    )

    dm = compute_demark(
        df, strat.demark.setup, strat.demark.countdown,
        strat.demark.setup_lookback, strat.demark.countdown_lookback,
    )
    rsi_zone = ((rsi >= strat.rsi.zone_low) & (rsi <= strat.rsi.zone_high)).to_numpy()

    return ConfluenceEvents(
        dates=dates, regime_gate=regime_gate, rsi_zone=rsi_zone,
        macd_hidden_bull=macd_hidden_bull, rsi_hidden_bull=rsi_hidden_bull,
        demark_td9_buy=dm["td9_buy"],
        demark_td13_sell=dm["td13_sell"], macd_regular_bear=macd_regular_bear,
        rsi_regular_bear=rsi_regular_bear, demark_td9_sell=dm["td9_sell"],
    )


# ── Signal computation (weights / thresholds / windows) ─────────────────────────

def _window_any(arr: np.ndarray, win: int) -> np.ndarray:
    """Vectorised 'did this event fire within the trailing `win` bars (incl. now)'."""
    n = len(arr)
    prefix = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(arr.astype(np.int64), out=prefix[1:])
    idx = np.arange(n)
    lo = np.maximum(0, idx - win + 1)
    return (prefix[idx + 1] - prefix[lo]) > 0


def compute_signals(ev: ConfluenceEvents, entry: EntryConfig, exit: ExitConfig) -> SignalArrays:
    """Turn events + weights/thresholds/windows into per-bar signals.

    Stateful only in the buy cooldown; everything else is vectorised.
    """
    n = ev.n
    ew = entry.weights
    xw = exit.weights

    e_mhb = _window_any(ev.macd_hidden_bull, entry.conf_window)
    e_rhb = _window_any(ev.rsi_hidden_bull, entry.conf_window)
    e_td9 = _window_any(ev.demark_td9_buy, entry.conf_window)
    zone = ev.rsi_zone  # location filter — current bar only

    entry_score = (
        ew.macd_hidden_bull * e_mhb + ew.rsi_hidden_bull * e_rhb
        + ew.rsi_zone * zone + ew.demark_td9_buy * e_td9
    ).astype(float)

    x_td13 = _window_any(ev.demark_td13_sell, exit.conf_window)
    x_mrb = _window_any(ev.macd_regular_bear, exit.conf_window)
    x_rrb = _window_any(ev.rsi_regular_bear, exit.conf_window)
    x_td9 = _window_any(ev.demark_td9_sell, exit.conf_window)

    exit_score = (
        xw.demark_td13_sell * x_td13 + xw.macd_regular_bear * x_mrb
        + xw.rsi_regular_bear * x_rrb + xw.demark_td9_sell * x_td9
    ).astype(float)

    entry_trigger = ev.macd_hidden_bull | ev.rsi_hidden_bull
    exit_trigger = ev.demark_td13_sell | ev.macd_regular_bear | ev.rsi_regular_bear | ev.demark_td9_sell
    both_div = ev.macd_hidden_bull & ev.rsi_hidden_bull

    buy_eligible = ev.regime_gate & entry_trigger & (entry_score >= entry.threshold)
    sell_fire = exit_trigger & (exit_score >= exit.threshold)

    signals: list[str] = ["Hold"] * n
    composite = np.zeros(n, dtype=float)
    cooldown = 0
    e_win = entry.conf_window
    for i in range(n):
        if cooldown > 0:
            cooldown -= 1
        if buy_eligible[i] and cooldown == 0 and not sell_fire[i]:
            signals[i] = "Strong Buy" if both_div[i] else "Buy"
            composite[i] = entry_score[i]
            cooldown = e_win
        elif sell_fire[i]:
            signals[i] = "Sell"
            composite[i] = -exit_score[i]

    fired = {
        "macd_hidden_bull": e_mhb, "rsi_hidden_bull": e_rhb,
        "rsi_zone": zone, "demark_td9_buy": e_td9,
        "demark_td13_sell": x_td13, "macd_regular_bear": x_mrb,
        "rsi_regular_bear": x_rrb, "demark_td9_sell": x_td9,
    }
    return SignalArrays(signals=signals, composite=composite,
                        entry_score=entry_score, exit_score=exit_score, fired=fired)


# ── Full engine (production: indicators → events → signals → audit rows) ─────────

def run_engine(
    df: pd.DataFrame,
    cfg: AppConfig,
    strategy: Literal["hidden_div"] = "hidden_div",
) -> list[dict]:
    """Run the confluence pipeline over a daily OHLCV DataFrame.

    Returns one auditable dict per bar, oldest → newest, each carrying:
    {date, signal, composite, entry_score, exit_score, regime, components, strategy}.
    """
    if df.empty:
        return []

    strat = cfg.get_strategy("hidden_div")
    ev = compute_events(df, strat)
    sa = compute_signals(ev, strat.entry, strat.exit)

    ew = strat.entry.weights
    xw = strat.exit.weights
    results: list[dict] = []
    for i in range(ev.n):
        components: dict[str, dict] = {}
        for name in ENTRY_COMPONENTS:
            w = float(getattr(ew, name))
            fired = bool(sa.fired[name][i])
            components[name] = {"side": "entry", "weight": w, "fired": fired,
                                "contribution": round(w * fired, 4)}
        for name in EXIT_COMPONENTS:
            w = float(getattr(xw, name))
            fired = bool(sa.fired[name][i])
            components[name] = {"side": "exit", "weight": w, "fired": fired,
                                "contribution": round(w * fired, 4)}

        results.append({
            "date": ev.dates[i],
            "signal": sa.signals[i],
            "composite": round(float(sa.composite[i]), 4),
            "entry_score": round(float(sa.entry_score[i]), 4),
            "exit_score": round(float(sa.exit_score[i]), 4),
            "regime": {"long_allowed": bool(ev.regime_gate[i]), "short_allowed": False},
            "components": components,
            "strategy": "hidden_div",
        })

    return results

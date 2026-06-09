"""Tests for the Hidden-Divergence Confluence signal engine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.config import load_config
from backend.app.scoring.confluence import (
    ConfluenceEvents,
    compute_signals,
    run_engine,
)


@pytest.fixture(scope="module")
def strat():
    return load_config().get_strategy("hidden_div")


def _events(n: int) -> ConfluenceEvents:
    z = lambda: np.zeros(n, dtype=bool)  # noqa: E731
    return ConfluenceEvents(
        dates=[str(i) for i in range(n)],
        regime_gate=z(), rsi_zone=z(),
        macd_hidden_bull=z(), rsi_hidden_bull=z(), demark_td9_buy=z(),
        demark_td13_sell=z(), macd_regular_bear=z(), rsi_regular_bear=z(), demark_td9_sell=z(),
    )


def test_both_divergences_fire_strong_buy(strat):
    ev = _events(30)
    ev.regime_gate[10] = True
    ev.macd_hidden_bull[10] = True
    ev.rsi_hidden_bull[10] = True
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[10] == "Strong Buy"
    assert sa.entry_score[10] == pytest.approx(70.0)  # 35 + 35
    assert sa.composite[10] == pytest.approx(70.0)


def test_single_divergence_below_threshold_holds(strat):
    ev = _events(30)
    ev.regime_gate[10] = True
    ev.macd_hidden_bull[10] = True  # 35 only, < 65 threshold
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[10] == "Hold"


def test_one_divergence_plus_supports_reaches_threshold(strat):
    ev = _events(30)
    ev.regime_gate[10] = True
    ev.macd_hidden_bull[10] = True   # 35 (also the trigger)
    ev.rsi_zone[10] = True           # 20
    ev.demark_td9_buy[10] = True     # 10  → 65 total
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[10] == "Buy"   # not Strong (only one divergence)
    assert sa.entry_score[10] == pytest.approx(65.0)


def test_no_buy_without_regime_gate(strat):
    ev = _events(30)
    ev.macd_hidden_bull[10] = True
    ev.rsi_hidden_bull[10] = True  # score 70 but gate is off
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[10] == "Hold"


def test_exit_fires_on_td13(strat):
    ev = _events(30)
    ev.demark_td13_sell[5] = True  # 40 ≥ 35
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[5] == "Sell"
    assert sa.exit_score[5] == pytest.approx(40.0)
    assert sa.composite[5] == pytest.approx(-40.0)


def test_lone_td9_sell_below_exit_threshold(strat):
    ev = _events(30)
    ev.demark_td9_sell[5] = True  # 20 < 35
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[5] == "Hold"


def test_cooldown_blocks_second_buy(strat):
    ev = _events(40)
    for k in (10, 12):  # within the 10-bar entry window
        ev.regime_gate[k] = True
        ev.macd_hidden_bull[k] = True
        ev.rsi_hidden_bull[k] = True
    sa = compute_signals(ev, strat.entry, strat.exit)
    assert sa.signals[10] in ("Buy", "Strong Buy")
    assert sa.signals[12] == "Hold"  # cooldown


def test_threshold_wiring(strat):
    ev = _events(30)
    ev.regime_gate[10] = True
    ev.macd_hidden_bull[10] = True  # 35
    lenient = strat.entry.model_copy(update={"threshold": 30.0})
    sa = compute_signals(ev, lenient, strat.exit)
    assert sa.signals[10] in ("Buy", "Strong Buy")  # 35 ≥ 30 now fires


def test_run_engine_contract():
    cfg = load_config()
    n = 260
    rng = np.random.default_rng(5)
    close = 50 * np.exp(np.cumsum(rng.normal(0.0006, 0.011, n)))
    idx = pd.bdate_range("2021-01-04", periods=n)
    df = pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1e6),
    }, index=idx)
    rows = run_engine(df, cfg)
    assert len(rows) == n
    r = rows[-1]
    assert set(r) >= {"date", "signal", "composite", "entry_score", "exit_score", "regime", "components"}
    assert r["regime"]["short_allowed"] is False
    assert len(r["components"]) == 8

"""Tests for the simplified DeMark TD Sequential."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.indicators.demark import compute_demark


def _df(close):
    n = len(close)
    close = np.asarray(close, dtype=float)
    high = close + 1.0
    low = close - 1.0
    idx = pd.RangeIndex(n)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": np.ones(n)}, index=idx)


def test_td9_buy_setup_completes_on_ninth_bar():
    # 4 flat bars, then 9 consecutive closes each below the close 4 bars earlier.
    close = [100, 100, 100, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91]
    dm = compute_demark(_df(close), setup=9, countdown=13, setup_lookback=4, countdown_lookback=2)
    assert dm["td9_buy"][12]  # the 9th qualifying close (index 12)
    assert dm["td9_buy"].sum() == 1
    assert dm["td9_sell"].sum() == 0


def test_td9_sell_setup_completes():
    close = [100, 100, 100, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
    dm = compute_demark(_df(close), setup=9, countdown=13, setup_lookback=4, countdown_lookback=2)
    assert dm["td9_sell"][12]
    assert dm["td9_buy"].sum() == 0


def test_broken_run_resets_setup():
    # A run that breaks before reaching 9 must not complete a setup.
    close = [100, 100, 100, 100, 99, 98, 97, 101, 96, 95, 94]
    dm = compute_demark(_df(close), setup=9, countdown=13, setup_lookback=4, countdown_lookback=2)
    assert dm["td9_buy"].sum() == 0


def test_no_lookahead_outputs_length_matches():
    close = list(range(50))
    dm = compute_demark(_df(close))
    assert all(len(v) == 50 for v in dm.values())


# ── TD13 countdown (use a short countdown so it completes before a re-setup) ─────

def test_td13_sell_countdown_completes_after_setup():
    # 4 flat + ascending → sell setup completes at bar 12, then countdown qualifies.
    close = [100, 100, 100, 100] + list(range(101, 121))
    dm = compute_demark(_df(close), setup=9, countdown=3, setup_lookback=4, countdown_lookback=2)
    assert dm["td9_sell"][12]
    sells = [i for i, v in enumerate(dm["td13_sell"]) if v]
    assert len(sells) >= 1
    assert sells[0] > 12  # countdown completes strictly after the setup


def test_td13_buy_countdown_completes_after_setup():
    close = [100, 100, 100, 100] + list(range(99, 79, -1))  # descending → buy setup
    dm = compute_demark(_df(close), setup=9, countdown=3, setup_lookback=4, countdown_lookback=2)
    assert dm["td9_buy"][12]
    buys = [i for i, v in enumerate(dm["td13_buy"]) if v]
    assert len(buys) >= 1 and buys[0] > 12


def test_td13_does_not_fire_without_setup():
    # Flat series → no setup → no countdown completion.
    close = [100] * 40
    dm = compute_demark(_df(close), setup=9, countdown=3, setup_lookback=4, countdown_lookback=2)
    assert dm["td13_sell"].sum() == 0
    assert dm["td13_buy"].sum() == 0

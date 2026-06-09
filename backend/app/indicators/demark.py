"""Simplified DeMark TD Sequential.

Implements ``V2-1/hidden_div_confluence_logic.md`` §7 and §11.  This is a
*simplified* port — setup + countdown in standard form with basic
opposite-setup cancellation; perfection, recycle, and other nuances are
deliberately omitted (and must stay omitted on the TradingView side too, or the
signals diverge).

Terms
-----
- **TD9 buy setup**  — ``setup`` consecutive closes, each LESS than the close
  ``setup_lookback`` bars earlier (downside exhaustion → boosts an entry).
- **TD9 sell setup** — ``setup`` consecutive closes, each GREATER than the close
  ``setup_lookback`` bars earlier (upside exhaustion → drives an exit).
- **TD13 sell countdown** — after a sell setup completes, count bars whose close
  ``>=`` the high ``countdown_lookback`` bars earlier; the 13th such bar completes
  the countdown (strong upside exhaustion → exit).
- **TD13 buy countdown** — mirror of the above (close ``<=`` low N bars back).

Each returned array marks the bar on which that event *completes*.  All values
at bar T use only bars ``<= T`` (no look-ahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_demark(
    df: pd.DataFrame,
    setup: int = 9,
    countdown: int = 13,
    setup_lookback: int = 4,
    countdown_lookback: int = 2,
) -> dict[str, np.ndarray]:
    """Return boolean completion arrays keyed ``td9_buy``, ``td9_sell``,
    ``td13_buy``, ``td13_sell`` (each length ``len(df)``)."""
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(close)

    td9_buy = np.zeros(n, dtype=bool)
    td9_sell = np.zeros(n, dtype=bool)
    td13_buy = np.zeros(n, dtype=bool)
    td13_sell = np.zeros(n, dtype=bool)

    buy_setup = 0
    sell_setup = 0
    buy_cd_active = False
    buy_cd_count = 0
    sell_cd_active = False
    sell_cd_count = 0

    for i in range(n):
        # ── Setups (need a close setup_lookback bars back) ──
        if i >= setup_lookback:
            buy_setup = buy_setup + 1 if close[i] < close[i - setup_lookback] else 0
            sell_setup = sell_setup + 1 if close[i] > close[i - setup_lookback] else 0

        if buy_setup == setup:
            td9_buy[i] = True
            buy_cd_active, buy_cd_count = True, 0
            sell_cd_active = False  # opposite setup cancels a pending sell countdown
            buy_setup = 0
        if sell_setup == setup:
            td9_sell[i] = True
            sell_cd_active, sell_cd_count = True, 0
            buy_cd_active = False  # opposite setup cancels a pending buy countdown
            sell_setup = 0

        # ── Countdowns (qualifier compares to high/low countdown_lookback bars back) ──
        if i >= countdown_lookback:
            if sell_cd_active and close[i] >= high[i - countdown_lookback]:
                sell_cd_count += 1
                if sell_cd_count >= countdown:
                    td13_sell[i] = True
                    sell_cd_active = False
            if buy_cd_active and close[i] <= low[i - countdown_lookback]:
                buy_cd_count += 1
                if buy_cd_count >= countdown:
                    td13_buy[i] = True
                    buy_cd_active = False

    return {
        "td9_buy": td9_buy,
        "td9_sell": td9_sell,
        "td13_buy": td13_buy,
        "td13_sell": td13_sell,
    }

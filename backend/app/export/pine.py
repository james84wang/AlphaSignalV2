"""Generate a TradingView **Pine Script v6** indicator from a strategy config.

This is the single source of truth for the ``.pine`` export. Both the static
``hidden_div_confluence_uptrend.pine`` checked into the repo and the in-app
"Download Pine Script" button call :func:`generate_pine`, so the exported script
**always reflects the current (tuned) config** — every ``input.*()`` default is
baked from ``config.yaml`` and the input name maps 1:1 to the AlphaSignal /
config key (``emaFast``, ``wMacd``, ``entryThreshold`` …).

The Pine logic is a faithful port of :mod:`backend.app.scoring.confluence` and
its indicators, so signals on TradingView match the Python backtest (allowing
for the deliberate ``lbR``-bar confirmation lag):

  * regime gate  → EMA-fast > EMA-slow, both rising, close > EMA-slow
  * divergence   → hidden-bull (entry) / regular-bear (exit) on confirmed swing
                   pivots, MACD line & RSI, gap within ``[minPivGap, maxPivGap]``
  * DeMark       → simplified TD9 setup + TD13 countdown (matches demark.py)
  * confluence   → component counts toward the score if it fired within the
                   window; cooldown == window blocks repeat buys
  * entry/exit   → weighted score vs. threshold

What does NOT port (TradingView-only eye-candy, irrelevant to signals): the S/R
zones described in the logic doc. They are intentionally omitted here.
"""
# This module emits Pine source; the generated plotshape/alert lines are
# legitimately long and must not be wrapped, so line-length is not enforced here.
# ruff: noqa: E501
from __future__ import annotations

from backend.app.config import StrategyConfig


def _fmt(x: float | int) -> str:
    """Render a number for a Pine literal: ``50`` not ``50.0``; keep real decimals."""
    f = float(x)
    if f.is_integer():
        return str(int(f))
    return repr(round(f, 6))


# ── Static logic block (no config values — those arrive via the inputs above) ────
# Pine has no curly braces, so this is safe to keep as a plain literal and append
# after the generated inputs.
_PINE_LOGIC = r'''
// ── Indicators ───────────────────────────────────────────────────────────────
emaF = ta.ema(close, emaFast)
emaS = ta.ema(close, emaSlow)
[macdLine, _macdSignal, _macdHist] = ta.macd(close, macdFast, macdSlow, macdSig)
rsiVal = ta.rsi(close, rsiLen)

// ── Regime gate (entries only) ───────────────────────────────────────────────
// EMA-fast above EMA-slow, both rising vs slopeLook bars ago, close above EMA-slow.
regimeGate = (emaF > emaS) and (emaF > emaF[slopeLook]) and (emaS > emaS[slopeLook]) and (close > emaS)

// ── Confirmed swing pivots (non-repainting: known lbR bars after they print) ──
pl = ta.pivotlow(low, lbL, lbR)
ph = ta.pivothigh(high, lbL, lbR)

// Last confirmed pivot LOW: price + bar + oscillator values at the pivot bar.
var float prevLowPrice = na
var int   prevLowBar   = na
var float prevLowMacd  = na
var float prevLowRsi   = na
// Last confirmed pivot HIGH.
var float prevHighPrice = na
var int   prevHighBar   = na
var float prevHighMacd  = na
var float prevHighRsi   = na

// Raw per-bar divergence events (true only on the confirmation bar).
bool macdHiddenBull  = false
bool rsiHiddenBull   = false
bool macdRegularBear = false
bool rsiRegularBear  = false

// Hidden-bullish: consecutive pivot lows, price higher-low, oscillator lower-low.
if not na(pl)
    curBar   = bar_index - lbR
    curPrice = pl
    curMacd  = macdLine[lbR]
    curRsi   = rsiVal[lbR]
    if not na(prevLowPrice)
        gap = curBar - prevLowBar
        if gap >= minPivGap and gap <= maxPivGap
            if curPrice > prevLowPrice and curMacd < prevLowMacd
                macdHiddenBull := true
            if curPrice > prevLowPrice and curRsi < prevLowRsi
                rsiHiddenBull := true
    prevLowPrice := curPrice
    prevLowBar   := curBar
    prevLowMacd  := curMacd
    prevLowRsi   := curRsi

// Regular-bearish: consecutive pivot highs, price higher-high, oscillator lower-high.
if not na(ph)
    curBar   = bar_index - lbR
    curPrice = ph
    curMacd  = macdLine[lbR]
    curRsi   = rsiVal[lbR]
    if not na(prevHighPrice)
        gap = curBar - prevHighBar
        if gap >= minPivGap and gap <= maxPivGap
            if curPrice > prevHighPrice and curMacd < prevHighMacd
                macdRegularBear := true
            if curPrice > prevHighPrice and curRsi < prevHighRsi
                rsiRegularBear := true
    prevHighPrice := curPrice
    prevHighBar   := curBar
    prevHighMacd  := curMacd
    prevHighRsi   := curRsi

// ── Simplified DeMark TD Sequential (mirrors demark.py exactly) ───────────────
var int  buySetup     = 0
var int  sellSetup    = 0
var bool buyCdActive  = false
var int  buyCdCount   = 0
var bool sellCdActive = false
var int  sellCdCount  = 0

bool td9Buy   = false
bool td9Sell  = false
bool td13Buy  = false
bool td13Sell = false

// Setups: tdSetup consecutive closes below / above the close tdFlipLook bars back.
if bar_index >= tdFlipLook
    buySetup  := close < close[tdFlipLook] ? buySetup + 1 : 0
    sellSetup := close > close[tdFlipLook] ? sellSetup + 1 : 0

if buySetup == tdSetup
    td9Buy       := true
    buyCdActive  := true
    buyCdCount   := 0
    sellCdActive := false   // opposite setup cancels a pending sell countdown
    buySetup     := 0
if sellSetup == tdSetup
    td9Sell      := true
    sellCdActive := true
    sellCdCount  := 0
    buyCdActive  := false   // opposite setup cancels a pending buy countdown
    sellSetup    := 0

// Countdowns: qualifier compares close to the high/low tdCountLook bars back.
if bar_index >= tdCountLook
    if sellCdActive and close >= high[tdCountLook]
        sellCdCount := sellCdCount + 1
        if sellCdCount >= tdCountdown
            td13Sell     := true
            sellCdActive := false
    if buyCdActive and close <= low[tdCountLook]
        buyCdCount := buyCdCount + 1
        if buyCdCount >= tdCountdown
            td13Buy     := true
            buyCdActive := false

// ── Confluence windows ("fired within the trailing window, incl. now") ───────
mhbBars  = ta.barssince(macdHiddenBull)
rhbBars  = ta.barssince(rsiHiddenBull)
td9bBars = ta.barssince(td9Buy)
e_mhb = not na(mhbBars)  and mhbBars  < confWin
e_rhb = not na(rhbBars)  and rhbBars  < confWin
e_td9 = not na(td9bBars) and td9bBars < confWin
zone  = rsiVal >= rsiZoneLo and rsiVal <= rsiZoneHi   // location filter (current bar)

td13Bars = ta.barssince(td13Sell)
mrbBars  = ta.barssince(macdRegularBear)
rrbBars  = ta.barssince(rsiRegularBear)
td9sBars = ta.barssince(td9Sell)
x_td13 = not na(td13Bars) and td13Bars < confWinX
x_mrb  = not na(mrbBars)  and mrbBars  < confWinX
x_rrb  = not na(rrbBars)  and rrbBars  < confWinX
x_td9  = not na(td9sBars) and td9sBars < confWinX

// ── Scores ───────────────────────────────────────────────────────────────────
entryScore = wMacd  * (e_mhb  ? 1 : 0) + wRsi  * (e_rhb ? 1 : 0) + wZone * (zone ? 1 : 0) + wTd9  * (e_td9 ? 1 : 0)
exitScore  = wTd13  * (x_td13 ? 1 : 0) + wMacdX * (x_mrb ? 1 : 0) + wRsiX * (x_rrb ? 1 : 0) + wTd9X * (x_td9 ? 1 : 0)

// ── Triggers + cooldown (mirrors compute_signals) ────────────────────────────
entryTrigger = macdHiddenBull or rsiHiddenBull
exitTrigger  = td13Sell or macdRegularBear or rsiRegularBear or td9Sell
bothDiv      = macdHiddenBull and rsiHiddenBull
buyEligible  = regimeGate and entryTrigger and entryScore >= entryThreshold
sellFire     = exitTrigger and exitScore  >= exitThreshold

var int cooldown = 0
bool isBuy       = false
bool isStrongBuy = false
bool isSell      = false
if cooldown > 0
    cooldown := cooldown - 1
if buyEligible and cooldown == 0 and not sellFire
    isBuy       := true
    isStrongBuy := bothDiv
    cooldown    := confWin
else if sellFire
    isSell := true

// ── Plots ────────────────────────────────────────────────────────────────────
plot(emaF, "EMA fast", color=color.new(color.blue, 0))
plot(emaS, "EMA slow", color=color.new(color.orange, 0))
bgcolor(regimeGate ? color.new(color.green, 92) : na, title="Regime uptrend")

plotshape(isBuy,  title="BUY",  style=shape.triangleup,   location=location.belowbar, color=isStrongBuy ? color.lime : color.green, size=size.small, text="BUY")
plotshape(isSell, title="SELL", style=shape.triangledown, location=location.abovebar, color=color.red, size=size.small, text="SELL")

showComp = input.bool(true, "Show component markers", group="Display")
plotshape(showComp and macdHiddenBull,  title="MACD hidden bull",  style=shape.circle,   location=location.belowbar, color=color.green,  size=size.tiny, text="M")
plotshape(showComp and rsiHiddenBull,   title="RSI hidden bull",   style=shape.square,   location=location.belowbar, color=color.teal,   size=size.tiny, text="R")
plotshape(showComp and macdRegularBear, title="MACD regular bear", style=shape.circle,   location=location.abovebar, color=color.red,    size=size.tiny, text="M")
plotshape(showComp and rsiRegularBear,  title="RSI regular bear",  style=shape.square,   location=location.abovebar, color=color.maroon, size=size.tiny, text="R")
plotshape(showComp and td9Buy,          title="TD9 buy",           style=shape.diamond,  location=location.belowbar, color=color.yellow, size=size.tiny, text="9")
plotshape(showComp and td9Sell,         title="TD9 sell",          style=shape.diamond,  location=location.abovebar, color=color.yellow, size=size.tiny, text="9")
plotshape(showComp and td13Sell,        title="TD13 sell",         style=shape.diamond,  location=location.abovebar, color=color.red,    size=size.tiny, text="13")

// ── Alerts (choose "Once Per Bar Close" when you create them) ────────────────
alertcondition(isBuy,  title="AlphaSignal BUY",  message="Hidden-divergence confluence BUY")
alertcondition(isSell, title="AlphaSignal SELL", message="Hidden-divergence confluence SELL")
if isBuy
    alert("AlphaSignal BUY "  + syminfo.ticker + " @ " + str.tostring(close, format.mintick) + "  entry score " + str.tostring(entryScore), alert.freq_once_per_bar_close)
if isSell
    alert("AlphaSignal SELL " + syminfo.ticker + " @ " + str.tostring(close, format.mintick) + "  exit score "  + str.tostring(exitScore),  alert.freq_once_per_bar_close)
'''


def generate_pine(strat: StrategyConfig, *, title: str | None = None) -> str:
    """Return the full Pine v6 script for ``strat`` (config baked into inputs)."""
    reg, piv, macd, rsi, dm = strat.regime, strat.pivots, strat.macd, strat.rsi, strat.demark
    ew, xw = strat.entry.weights, strat.exit.weights
    en, ex = strat.entry, strat.exit
    name = title or "AlphaSignal — Hidden-Divergence Confluence (Uptrend Swing)"

    header = f'''//@version=6
// =============================================================================
// {name}
// Auto-generated by AlphaSignal from config.yaml (profile: hidden_div).
// Every input default below is your current tuned value; each input name maps
// 1:1 to the AlphaSignal config key, so this script and the Python backtest use
// the SAME numbers. Signals lag the actual turn by lbR bars (non-repainting).
//
// PRICE BASIS: match the close you backtest on. yfinance uses adjusted close by
// default — set TradingView chart ▸ Settings ▸ Symbol ▸ "Adjust data for
// dividends" to the same choice, or the two will drift over long histories.
// =============================================================================
indicator("{name}", shorttitle="AlphaSignal HDC", overlay=true, max_labels_count=500)

// ── Regime ───────────────────────────────────────────────────────────────────
emaFast   = input.int({_fmt(reg.ema_fast)}, "EMA fast (emaFast)",  minval=1, group="Regime")
emaSlow   = input.int({_fmt(reg.ema_slow)}, "EMA slow (emaSlow)",  minval=1, group="Regime")
slopeLook = input.int({_fmt(reg.slope_lookback)}, "EMA slope lookback (slopeLook)", minval=1, group="Regime")

// ── Swing pivots ─────────────────────────────────────────────────────────────
lbL       = input.int({_fmt(piv.left)},  "Pivot left bars (lbL)",  minval=1, group="Pivots")
lbR       = input.int({_fmt(piv.right)}, "Pivot right bars / confirmation lag (lbR)", minval=1, group="Pivots")
minPivGap = input.int({_fmt(piv.min_bars)}, "Min bars between pivots (minPivGap)", minval=1, group="Pivots")
maxPivGap = input.int({_fmt(piv.max_bars)}, "Max bars between pivots (maxPivGap)", minval=1, group="Pivots")

// ── MACD ─────────────────────────────────────────────────────────────────────
macdFast  = input.int({_fmt(macd.fast)},   "MACD fast (macdFast)", minval=1, group="MACD")
macdSlow  = input.int({_fmt(macd.slow)},   "MACD slow (macdSlow)", minval=1, group="MACD")
macdSig   = input.int({_fmt(macd.signal)}, "MACD signal (macdSig)", minval=1, group="MACD")

// ── RSI ──────────────────────────────────────────────────────────────────────
rsiLen    = input.int({_fmt(rsi.period)},   "RSI length (rsiLen)", minval=1, group="RSI")
rsiZoneLo = input.float({_fmt(rsi.zone_low)},  "RSI buy-zone low (rsiZoneLo)",  group="RSI")
rsiZoneHi = input.float({_fmt(rsi.zone_high)}, "RSI buy-zone high (rsiZoneHi)", group="RSI")

// ── DeMark TD Sequential ─────────────────────────────────────────────────────
tdSetup     = input.int({_fmt(dm.setup)},      "TD setup length (tdSetup)", minval=1, group="DeMark")
tdCountdown = input.int({_fmt(dm.countdown)},  "TD countdown length (tdCountdown)", minval=1, group="DeMark")
tdFlipLook  = input.int({_fmt(dm.setup_lookback)},     "TD setup compare lookback (tdFlipLook)", minval=1, group="DeMark")
tdCountLook = input.int({_fmt(dm.countdown_lookback)}, "TD countdown compare lookback (tdCountLook)", minval=1, group="DeMark")

// ── Entry (BUY) weights + threshold ──────────────────────────────────────────
wMacd = input.float({_fmt(ew.macd_hidden_bull)}, "MACD hidden-bull weight (wMacd)", group="Entry weights")
wRsi  = input.float({_fmt(ew.rsi_hidden_bull)},  "RSI hidden-bull weight (wRsi)",  group="Entry weights")
wZone = input.float({_fmt(ew.rsi_zone)},         "RSI buy-zone weight (wZone)",    group="Entry weights")
wTd9  = input.float({_fmt(ew.demark_td9_buy)},   "TD9 buy weight (wTd9)",          group="Entry weights")
entryThreshold = input.float({_fmt(en.threshold)}, "Buy threshold (entryThreshold)", group="Entry")
confWin        = input.int({_fmt(en.conf_window)}, "Entry confluence window + cooldown (confWin)", minval=1, group="Entry")

// ── Exit (SELL) weights + threshold ──────────────────────────────────────────
wMacdX = input.float({_fmt(xw.macd_regular_bear)}, "MACD regular-bear weight (wMacdX)", group="Exit weights")
wRsiX  = input.float({_fmt(xw.rsi_regular_bear)},  "RSI regular-bear weight (wRsiX)",  group="Exit weights")
wTd13  = input.float({_fmt(xw.demark_td13_sell)},  "TD13 sell weight (wTd13)",         group="Exit weights")
wTd9X  = input.float({_fmt(xw.demark_td9_sell)},   "TD9 sell weight (wTd9X)",          group="Exit weights")
exitThreshold = input.float({_fmt(ex.threshold)}, "Sell threshold (exitThreshold)", group="Exit")
confWinX      = input.int({_fmt(ex.conf_window)}, "Exit confluence window + cooldown (confWinX)", minval=1, group="Exit")
'''

    return header + _PINE_LOGIC

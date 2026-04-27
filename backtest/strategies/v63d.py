"""Reimplementation of bybit_live_bot.py v6.3d for backtesting.

Faithful to the live bot's logic: 15m primary, 1h MTF, 1d SHORT filter,
ATR-based dynamic stops, stepped trailing, asymmetric long/short sizing.
Uses indicator-based mode detection (strong_trend / sideways / pullback).

Note: pyramiding and limit-order delays are NOT modeled (close-of-bar market
fills only). Fee/slippage applied via engine config.
"""
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd

# Live bot constants (v6.3d)
ADX_STRONG = 25.0
ADX_STRONG_HOLD = 25.0
ADX_SHORT_STRONG = 35.0
BB_STRONG = 0.020
DI_GAP = 10.0
ATR_VOL_MULT = 1.8

ST_SL_PCT = 0.006
SW_SL_PCT = 0.004
SW_TP_MIN = 0.010
SW_TP_MAX = 0.025
FLASH_CRASH = 0.025

LONG_SIZE_MULT = 1.10
SHORT_SIZE_MULT = 0.30
ST_SIZE_PCT = 0.38
SW_SIZE_PCT = 0.28

PULLBACK_BAND = 0.005
EMA_DIST_MAX = 0.015
STABILITY_N = 1

SL_ATR_MULT = 1.3       # BTC sym_cfg
SL_ATR_MIN = 0.005
SL_ATR_MAX = 0.012
VOLUME_MIN = 1.3
ADX_STRONG_BTC = 27.0
COOLDOWN_SEC_BTC = 1800
MIN_HOLD_SEC = 90
STRONG_REENTRY_MIN = 20

LEVERAGE = 7.0

TRAIL_LEVELS = [
    (0.008, 0.004),
    (0.015, 0.005),
    (0.025, 0.007),
    (0.040, 0.010),
    (0.060, 0.015),
]


def _detect_mode(row, current_mode: str = "") -> str:
    adx = row.adx
    bb_w = row.bb_width
    di_p = row.di_plus
    di_m = row.di_minus
    atr_pct = row.atr_pct
    atr_ma = row.atr_ma
    if pd.isna(adx) or pd.isna(bb_w):
        return "unclear"
    di_gap = abs(di_p - di_m)
    atr_ratio = atr_pct / atr_ma if atr_ma and atr_ma > 0 else 1
    if atr_ratio > ATR_VOL_MULT or bb_w > 0.05:
        return "high_vol"
    if current_mode == "strong_trend":
        if adx >= ADX_STRONG_HOLD and bb_w > BB_STRONG and di_gap > DI_GAP:
            return "strong_trend"
    if current_mode == "sideways":
        if adx <= 23 and 0.010 < bb_w < 0.028:
            return "sideways"
    if adx > ADX_STRONG_BTC and bb_w > BB_STRONG and di_gap > DI_GAP:
        return "strong_trend"
    if adx < 22 and 0.010 < bb_w < 0.028:
        return "sideways"
    return "unclear"


def _h1_uptrend(row_h1) -> bool:
    if row_h1 is None or pd.isna(row_h1.get("ema20", np.nan)):
        return False
    return row_h1.ema20 > row_h1.ema50


def _h1_downtrend(row_h1) -> bool:
    if row_h1 is None or pd.isna(row_h1.get("ema20", np.nan)):
        return False
    return row_h1.ema20 < row_h1.ema50


def _is_daily_bearish(row_d1) -> bool:
    if row_d1 is None: return False
    if pd.isna(row_d1.get("close", np.nan)) or pd.isna(row_d1.get("ema50", np.nan)):
        return False
    sma50_now = row_d1.ema50
    sma50_prev = row_d1.get("ema50_prev5", sma50_now)
    return (row_d1.close < sma50_now) and (sma50_now < sma50_prev)


def _strong_signal(row, daily_bearish: bool) -> str:
    ema_long = row.ema20 > row.ema50
    ema_short = row.ema20 < row.ema50
    di_long = row.di_plus > row.di_minus + DI_GAP
    di_short = row.di_minus > row.di_plus + DI_GAP
    bb_pos = row.bb_pos
    long_ok = ema_long and di_long and row.rsi < 68 and bb_pos < 0.65
    short_basic = (ema_short and di_short and row.rsi > 32 and bb_pos > 0.35
                   and row.adx >= ADX_SHORT_STRONG)
    short_ok = short_basic and daily_bearish
    if long_ok: return "LONG"
    if short_ok: return "SHORT"
    return "NONE"


def _sideways_signal(row) -> str:
    vw = row.vol_ratio < 0.85
    body = row.body if row.body > 0 else 1e-9
    uw = row.upper_wick > body * 0.5
    lw = row.lower_wick > body * 0.5
    rdt = row.rsi < row.rsi_h5 * 0.97
    rdb = row.rsi > row.rsi_l5 * 1.03
    if row.bb_pos > 0.92 and row.rsi > 65 and sum([vw, uw, rdt]) >= 2:
        return "SHORT"
    if row.bb_pos < 0.15 and row.rsi < 42 and sum([vw, lw, rdb]) >= 2:
        return "LONG"
    return "NONE"


def _pullback_signal(row, row_h1, daily_bearish: bool) -> str:
    if row_h1 is None: return "NONE"
    if pd.isna(row_h1.get("ema20", np.nan)) or pd.isna(row_h1.get("ema50", np.nan)):
        return "NONE"
    near = abs(row.close - row.ema20) / row.ema20 <= PULLBACK_BAND
    if not near: return "NONE"
    if row_h1.ema20 > row_h1.ema50 and row.rsi < 60 and row.bb_pos < 0.65:
        return "LONG"
    if (row_h1.ema20 < row_h1.ema50 and row.rsi > 40 and row.bb_pos > 0.35
            and daily_bearish and row.adx >= ADX_SHORT_STRONG):
        return "SHORT"
    return "NONE"


def make_strategy():
    """Closure holding mode history + cooldowns across calls."""
    state = {
        "mode_hist": [],
        "prev_mode": "",
        "last_exit_idx": -10_000,
        "strong_sl_idx": -10_000,
        "consec_loss": 0,
        "cooldown_until": -1,
        "last_pos_id": 0,
    }

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        df_h1 = ctx["df_1h"]
        df_d1 = ctx["df_1d"]
        pos = ctx["position"]
        row = df.iloc[i]
        row_h1 = df_h1.iloc[i] if df_h1 is not None else None
        row_d1 = df_d1.iloc[i] if df_d1 is not None else None

        # ---- Manage open position ----
        if pos is not None:
            entry = pos.entry
            side = pos.side
            close = ctx["close"]
            high = ctx["high"]
            low = ctx["low"]
            if side == "long":
                pnl_pct = (close - entry) / entry
                peak_pct = (high - entry) / entry
            else:
                pnl_pct = (entry - close) / entry
                peak_pct = (entry - low) / entry
            if peak_pct > pos.peak:
                pos.peak = peak_pct

            mode = pos.tag

            # Flash crash
            if pnl_pct <= -FLASH_CRASH:
                return {"action": "close", "reason": "flash"}

            if mode == "strong_trend" or mode == "pullback":
                # Trailing stops via modify_stop
                peak = pos.peak
                if peak >= TRAIL_LEVELS[0][0]:
                    cb = TRAIL_LEVELS[-1][1]
                    for thr, c in TRAIL_LEVELS:
                        if peak >= thr:
                            cb = c
                    # Compute stop level corresponding to "current price < peak - cb"
                    if side == "long":
                        new_stop = entry * (1 + peak - cb)
                        if new_stop > pos.stop:
                            return {"action": "modify_stop", "stop": new_stop}
                    else:
                        new_stop = entry * (1 - peak + cb)
                        if new_stop < pos.stop:
                            return {"action": "modify_stop", "stop": new_stop}
            elif mode == "sideways":
                # TP via modify (stop already set at entry; tp via direct close trigger handled by engine if pos.tp)
                # Trail when peak >= 0.6%
                peak = pos.peak
                if peak >= 0.006:
                    cb = 0.003
                    if side == "long":
                        new_stop = entry * (1 + peak - cb)
                        if new_stop > pos.stop:
                            return {"action": "modify_stop", "stop": new_stop}
                    else:
                        new_stop = entry * (1 - peak + cb)
                        if new_stop < pos.stop:
                            return {"action": "modify_stop", "stop": new_stop}
            return None

        # ---- Cooldown ----
        if i < state["cooldown_until"]:
            return None
        # Coin cooldown: 30 min = 120 bars of 15m
        if i - state["last_exit_idx"] < 120:
            return None
        # Strong SL re-entry cooldown: 20 min = 80 bars
        if i - state["strong_sl_idx"] < 80:
            pass  # only for pullback/strong, will check below

        # ---- Mode detection ----
        cur = _detect_mode(row, current_mode=state["prev_mode"])
        state["mode_hist"].append(cur)
        if len(state["mode_hist"]) > 20:
            state["mode_hist"] = state["mode_hist"][-20:]
        state["prev_mode"] = cur

        # Stability filter: STABILITY_N=1 in v6.3d (no constraint really)
        # 1h MTF: skip simplified — assume aligned
        if cur in ("unclear", "high_vol"):
            # Try pullback if PULLBACK_MODE
            db = _is_daily_bearish(row_d1)
            psig = _pullback_signal(row, row_h1, db)
            if psig == "NONE":
                return None
            sig = psig
            mode_tag = "pullback"
        elif cur == "strong_trend":
            db = _is_daily_bearish(row_d1)
            sig = _strong_signal(row, db)
            if sig == "NONE":
                return None
            # EMA distance filter
            ema_dist = abs(row.close - row.ema20) / row.ema20
            if sig == "LONG" and row.close > row.ema20 and ema_dist > EMA_DIST_MAX:
                return None
            if sig == "SHORT" and row.close < row.ema20 and ema_dist > EMA_DIST_MAX:
                return None
            mode_tag = "strong_trend"
        elif cur == "sideways":
            sig = _sideways_signal(row)
            if sig == "NONE":
                return None
            mode_tag = "sideways"
        else:
            return None

        # Strong SL re-entry cooldown
        if mode_tag in ("strong_trend", "pullback"):
            if i - state["strong_sl_idx"] < 80:
                return None

        # Volume filter (strong & pullback)
        if mode_tag in ("strong_trend", "pullback"):
            if row.vol_ratio < VOLUME_MIN:
                return None

        # Stop calculation
        atr = row.atr
        price = row.close
        if mode_tag == "strong_trend" or mode_tag == "pullback":
            sl_pct = max(SL_ATR_MIN, min(SL_ATR_MAX, (atr * SL_ATR_MULT) / price))
        else:
            sl_pct = SW_SL_PCT

        side = "long" if sig == "LONG" else "short"
        if side == "long":
            stop = price * (1 - sl_pct)
        else:
            stop = price * (1 + sl_pct)

        # TP for sideways (BB midline 70%)
        tp = None
        if mode_tag == "sideways":
            if side == "long":
                raw_tp = max(0, (row.bb_mid - price) / price * 0.70)
            else:
                raw_tp = max(0, (price - row.bb_mid) / price * 0.70)
            tp_pct = max(SW_TP_MIN, min(SW_TP_MAX, raw_tp if raw_tp > 0 else SW_TP_MIN))
            tp = price * (1 + tp_pct) if side == "long" else price * (1 - tp_pct)

        # Size: with risk_per_trade enabled in engine, size_pct fallback is used only if disabled.
        # Live bot uses fraction-of-equity sizing; we replicate via use_risk_sizing=False alternate.
        if mode_tag == "strong_trend" or mode_tag == "pullback":
            base = ST_SIZE_PCT * (0.78 if mode_tag == "pullback" else 1.0)
        else:
            base = SW_SIZE_PCT
        mult = LONG_SIZE_MULT if side == "long" else SHORT_SIZE_MULT
        size_pct = base * mult

        return {
            "action": "open", "side": side,
            "stop": stop, "tp": tp,
            "size_pct": size_pct,
            "tag": mode_tag,
        }

    return strat

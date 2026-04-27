"""Strategy A: 1H structure swing.

Premise: trade in direction of 4H trend, enter on retracement to 1H value zone,
trigger on 1H momentum reset (RSI cross + bullish/bearish candle), structural stop.

Rules
-----
Trend filter (4H):
  Long bias  : close > EMA200 and EMA50 > EMA200
  Short bias : close < EMA200 and EMA50 < EMA200
  No trade   : otherwise (chop / regime transition)

Setup zone (1H):
  Long  : low touched a band [EMA20 - 0.3*ATR, EMA20 + 0.3*ATR] within last 4 bars
          and current close > EMA20
  Short : symmetric (mirror)

Trigger (15m):
  Long  : 15m close > prior 15m high  AND 15m bullish candle (close > open)
          AND 1h RSI between 40 and 65  AND volume ratio > 1.0
  Short : symmetric (RSI between 35-60)

Volatility filter:
  4H ATR percentile (rolling 120 bars, ~20 days) >= 0.30 (skip dead-vol regimes)

Risk:
  stop = swing_low_5bar - 0.25*ATR(1h)  (long)  /  swing_high + 0.25*ATR (short)
  TP1  = entry + 1R, partial 50%  -> implemented via TP at 1R + trail rest
  TP2  : trail by 1.5*ATR(1h) Chandelier
  risk per trade = 1% of equity (engine handles sizing via stop distance)
  max leverage = 5x
"""
from __future__ import annotations
import numpy as np
import pandas as pd

ATR_TRAIL_MULT = 1.5
ATR_STOP_BUFFER = 0.25
SETUP_LOOKBACK = 4
ATR_PCTILE_MIN = 0.30
RSI_LONG_RANGE = (40, 65)
RSI_SHORT_RANGE = (35, 60)
SWING_LOOKBACK = 5
TP1_R = 1.0
COOLDOWN_BARS = 16   # 4 hours after exit


def make_strategy():
    state = {"last_exit_idx": -10_000, "tp1_done": False}

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        h1 = ctx["df_1h"]
        h4 = ctx["df_4h"]
        pos = ctx["position"]
        row = df.iloc[i]
        row_h1 = h1.iloc[i] if h1 is not None else None
        row_h4 = h4.iloc[i] if h4 is not None else None

        # ---- Manage open position ----
        if pos is not None:
            close = ctx["close"]
            high = ctx["high"]
            low = ctx["low"]
            if pos.side == "long":
                pnl_R = (close - pos.entry) / (pos.entry - pos.extras["init_stop"])
                # TP1 partial -> we approximate by moving stop to breakeven on +1R
                if not pos.extras.get("tp1_done") and pnl_R >= TP1_R:
                    pos.extras["tp1_done"] = True
                    new_stop = pos.entry  # breakeven
                    if new_stop > pos.stop:
                        return {"action": "modify_stop", "stop": new_stop}
                # Chandelier trail
                if pos.extras.get("tp1_done"):
                    atr_h1 = row_h1.atr if row_h1 is not None and not pd.isna(row_h1.atr) else 0
                    if atr_h1 > 0:
                        candidate = high - ATR_TRAIL_MULT * atr_h1
                        if candidate > pos.stop:
                            return {"action": "modify_stop", "stop": candidate}
            else:
                pnl_R = (pos.entry - close) / (pos.extras["init_stop"] - pos.entry)
                if not pos.extras.get("tp1_done") and pnl_R >= TP1_R:
                    pos.extras["tp1_done"] = True
                    new_stop = pos.entry
                    if new_stop < pos.stop:
                        return {"action": "modify_stop", "stop": new_stop}
                if pos.extras.get("tp1_done"):
                    atr_h1 = row_h1.atr if row_h1 is not None and not pd.isna(row_h1.atr) else 0
                    if atr_h1 > 0:
                        candidate = low + ATR_TRAIL_MULT * atr_h1
                        if candidate < pos.stop:
                            return {"action": "modify_stop", "stop": candidate}
            return None

        # ---- Cooldown after exit ----
        if i - state["last_exit_idx"] < COOLDOWN_BARS:
            return None

        # ---- Trend filter (4H) ----
        if row_h4 is None or pd.isna(row_h4.get("ema200", np.nan)):
            return None
        ema200_4h = row_h4.ema200
        ema50_4h = row_h4.ema50
        close_4h = row_h4.close
        long_bias = (close_4h > ema200_4h) and (ema50_4h > ema200_4h)
        short_bias = (close_4h < ema200_4h) and (ema50_4h < ema200_4h)
        if not (long_bias or short_bias):
            return None

        # Vol filter
        atr_pctile = row_h4.get("atr_pct_pctile", 0.5)
        if pd.isna(atr_pctile) or atr_pctile < ATR_PCTILE_MIN:
            return None

        # ---- Setup zone (1H) ----
        if row_h1 is None or pd.isna(row_h1.get("ema20", np.nan)):
            return None
        ema20_h1 = row_h1.ema20
        atr_h1 = row_h1.atr
        if pd.isna(atr_h1) or atr_h1 <= 0:
            return None
        band_lo = ema20_h1 - 0.3 * atr_h1
        band_hi = ema20_h1 + 0.3 * atr_h1

        # Lookback over last SETUP_LOOKBACK 1H bars (= 4*SETUP_LOOKBACK 15m bars)
        h1_window = h1.iloc[max(0, i - 4 * SETUP_LOOKBACK):i + 1]
        if len(h1_window) < SETUP_LOOKBACK:
            return None
        recently_in_zone_long = (h1_window["low"] <= band_hi).any() and (h1_window["low"] >= band_lo - atr_h1).any()
        recently_in_zone_short = (h1_window["high"] >= band_lo).any() and (h1_window["high"] <= band_hi + atr_h1).any()

        # ---- 1H RSI gate ----
        rsi_h1 = row_h1.rsi
        if pd.isna(rsi_h1):
            return None

        # ---- 15m trigger ----
        prev_high = df["high"].iloc[i - 1]
        prev_low = df["low"].iloc[i - 1]
        bullish_candle = row.close > row.open
        bearish_candle = row.close < row.open
        vol_ok = row.vol_ratio >= 1.0 if not pd.isna(row.vol_ratio) else False

        if long_bias and recently_in_zone_long and row.close > ema20_h1:
            if (RSI_LONG_RANGE[0] <= rsi_h1 <= RSI_LONG_RANGE[1]
                    and bullish_candle and row.close > prev_high and vol_ok):
                # Stop: swing low last 5 bars on 15m - buffer
                swing_lo = df["low"].iloc[max(0, i - SWING_LOOKBACK):i].min()
                stop = swing_lo - ATR_STOP_BUFFER * atr_h1 / 4  # 1/4 since 15m vs 1H
                if stop >= row.close:
                    return None
                return {
                    "action": "open", "side": "long",
                    "stop": float(stop), "tp": None,
                    "tag": "A_long",
                    "extras": {"init_stop": float(stop), "tp1_done": False},
                }

        if short_bias and recently_in_zone_short and row.close < ema20_h1:
            if (RSI_SHORT_RANGE[0] <= rsi_h1 <= RSI_SHORT_RANGE[1]
                    and bearish_candle and row.close < prev_low and vol_ok):
                swing_hi = df["high"].iloc[max(0, i - SWING_LOOKBACK):i].max()
                stop = swing_hi + ATR_STOP_BUFFER * atr_h1 / 4
                if stop <= row.close:
                    return None
                return {
                    "action": "open", "side": "short",
                    "stop": float(stop), "tp": None,
                    "tag": "A_short",
                    "extras": {"init_stop": float(stop), "tp1_done": False},
                }

        return None

    return strat

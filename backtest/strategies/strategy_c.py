"""Strategy C: 15m Donchian breakout (satellite).

Premise: trade 15m Donchian-20 breakouts in direction of 1H trend with vol confirmation.
Use ATR stop and a fixed R:R take-profit. Higher trade frequency, smaller per-trade risk.

Rules
-----
Trend (1H): close > EMA50 = uptrend; close < EMA50 = downtrend; else skip
Breakout (15m): close > Donchian-20 high (long) or < Donchian-20 low (short),
                where Donchian is computed on the 20 bars BEFORE current
Vol filter: vol_ratio >= 1.3 on 15m
ATR filter: 15m atr_pct in [0.001, 0.020]  (skip dead vol AND chaotic vol)

Risk:
  stop = entry +/- 1.5 * ATR(15m, 14)
  tp   = entry +/- 3.0 * ATR(15m, 14)   (2R fixed)
  break-even at +1R, then trail by 1.0 * ATR
  risk per trade = 0.5% of equity
  cooldown after stop = 8 bars (2 hours)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

DONCHIAN_N = 20
ATR_STOP_MULT = 1.5
ATR_TP_MULT = 3.0
ATR_TRAIL_MULT = 1.0
COOLDOWN_BARS_LOSS = 8
VOL_MIN = 1.3
ATR_PCT_MIN = 0.001
ATR_PCT_MAX = 0.020


def make_strategy():
    state = {"last_loss_idx": -10_000}

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        h1 = ctx["df_1h"]
        pos = ctx["position"]
        row = df.iloc[i]
        row_h1 = h1.iloc[i] if h1 is not None else None

        if pos is not None:
            close = ctx["close"]
            high = ctx["high"]
            low = ctx["low"]
            atr15 = row.atr if not pd.isna(row.atr) else 0
            init_stop = pos.extras.get("init_stop", pos.stop)
            R = abs(pos.entry - init_stop)
            if R <= 0:
                return None
            if pos.side == "long":
                pnl = close - pos.entry
                if not pos.extras.get("be_done") and pnl >= R:
                    pos.extras["be_done"] = True
                    return {"action": "modify_stop", "stop": pos.entry}
                if pos.extras.get("be_done") and atr15 > 0:
                    cand = high - ATR_TRAIL_MULT * atr15
                    if cand > pos.stop:
                        return {"action": "modify_stop", "stop": cand}
            else:
                pnl = pos.entry - close
                if not pos.extras.get("be_done") and pnl >= R:
                    pos.extras["be_done"] = True
                    return {"action": "modify_stop", "stop": pos.entry}
                if pos.extras.get("be_done") and atr15 > 0:
                    cand = low + ATR_TRAIL_MULT * atr15
                    if cand < pos.stop:
                        return {"action": "modify_stop", "stop": cand}
            return None

        if i - state["last_loss_idx"] < COOLDOWN_BARS_LOSS:
            return None

        if row_h1 is None or pd.isna(row_h1.get("ema50", np.nan)):
            return None
        atr15 = row.atr
        if pd.isna(atr15) or atr15 <= 0: return None
        atr_pct = atr15 / row.close
        if not (ATR_PCT_MIN <= atr_pct <= ATR_PCT_MAX):
            return None
        if pd.isna(row.vol_ratio) or row.vol_ratio < VOL_MIN:
            return None

        prior = df.iloc[max(0, i - DONCHIAN_N):i]
        if len(prior) < DONCHIAN_N: return None
        donch_hi = prior["high"].max()
        donch_lo = prior["low"].min()

        long_trend = row_h1.close > row_h1.ema50
        short_trend = row_h1.close < row_h1.ema50

        if long_trend and row.close > donch_hi:
            stop = row.close - ATR_STOP_MULT * atr15
            tp = row.close + ATR_TP_MULT * atr15
            return {"action": "open", "side": "long",
                    "stop": float(stop), "tp": float(tp),
                    "tag": "C_long",
                    "extras": {"init_stop": float(stop), "be_done": False}}
        if short_trend and row.close < donch_lo:
            stop = row.close + ATR_STOP_MULT * atr15
            tp = row.close - ATR_TP_MULT * atr15
            return {"action": "open", "side": "short",
                    "stop": float(stop), "tp": float(tp),
                    "tag": "C_short",
                    "extras": {"init_stop": float(stop), "be_done": False}}
        return None

    return strat

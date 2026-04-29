"""Strategy MR (Mean Reversion) — pairs with D for choppy regimes.

Premise: D is trend-following (silent in chop). MR fires *opposite* signals
when price stretches to BB extremes during low-trend conditions. The two
strategies have low correlation by design — D wants ADX high, MR wants
ADX low. Combined coverage across regimes.

Rules (15m primary, 1h context optional)
----------------------------------------
Setup conditions (ALL must be true):
  ADX < 25                          (choppy, not strong trend)
  not (4H strong trend opposite)    (don't fight the elephant)

Long signal:
  bb_pos < 0.10                     (price near lower BB)
  RSI < 30                          (oversold)
  current 15m candle bullish        (close > open, reversal in progress)

Short signal:
  bb_pos > 0.90                     (price near upper BB)
  RSI > 70                          (overbought)
  current 15m candle bearish

Risk:
  stop = entry +/- 1.5 * ATR(15m)
  tp   = BB middle line             (snap-back to mean)
  cooldown after stop loss: 4 bars (1h)
  cooldown after tp:        2 bars (30 min)
  leverage: 2x (modest — counter-trend setups always carry tail risk)
  risk per trade: 0.5%
"""
from __future__ import annotations
import numpy as np
import pandas as pd

ATR_STOP_MULT = 1.5
ADX_CHOP_MAX = 25.0
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
BB_POS_LOW = 0.10
BB_POS_HIGH = 0.90
COOLDOWN_BARS_LOSS = 4
COOLDOWN_BARS_WIN = 2
LEV = 2.0
RISK = 0.005


def _check_signal(row, row_h4) -> tuple[str, str]:
    """Returns (side 'long'|'short'|'none', reason)."""
    if pd.isna(row.adx) or pd.isna(row.bb_pos) or pd.isna(row.rsi):
        return "none", "nan"

    if row.adx >= ADX_CHOP_MAX:
        return "none", f"adx {row.adx:.1f} too high (chop required)"

    bullish = row.close > row.open
    bearish = row.close < row.open

    # 4H opposite-trend block (don't short in 4H bull, don't long in 4H bear)
    h4_strong_up = False
    h4_strong_down = False
    if row_h4 is not None and not pd.isna(row_h4.get("ema200", np.nan)):
        h4_strong_up = (row_h4.close > row_h4.ema200) and (row_h4.ema50 > row_h4.ema200)
        h4_strong_down = (row_h4.close < row_h4.ema200) and (row_h4.ema50 < row_h4.ema200)

    if row.bb_pos < BB_POS_LOW and row.rsi < RSI_OVERSOLD and bullish:
        if h4_strong_down:
            return "none", "4H strong down — long blocked"
        return "long", "oversold + reversal"

    if row.bb_pos > BB_POS_HIGH and row.rsi > RSI_OVERBOUGHT and bearish:
        if h4_strong_up:
            return "none", "4H strong up — short blocked"
        return "short", "overbought + reversal"

    return "none", "no extreme"


def make_strategy():
    state = {"last_loss_idx": -10_000, "last_win_idx": -10_000}

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        h4 = ctx["df_4h"]
        pos = ctx["position"]
        cfg = ctx["cfg"]
        row = df.iloc[i]
        row_h4 = h4.iloc[i] if h4 is not None else None

        # ----- manage open position -----
        if pos is not None:
            close = ctx["close"]
            atr15 = row.atr if not pd.isna(row.atr) else 0
            init_stop = pos.extras.get("init_stop", pos.stop)
            R = abs(pos.entry - init_stop)
            if R <= 0:
                return None

            # TP target = BB middle (already set in pos.tp at entry, engine handles)
            # No trailing for MR — pure mean reversion, exit at mean
            return None

        # ----- cooldowns -----
        if i - state["last_loss_idx"] < COOLDOWN_BARS_LOSS:
            return None
        if i - state["last_win_idx"] < COOLDOWN_BARS_WIN:
            return None

        side, reason = _check_signal(row, row_h4)
        if side == "none":
            return None

        atr15 = row.atr
        if pd.isna(atr15) or atr15 <= 0:
            return None

        if side == "long":
            stop = row.close - ATR_STOP_MULT * atr15
            tp = row.bb_mid     # snap to mean
        else:
            stop = row.close + ATR_STOP_MULT * atr15
            tp = row.bb_mid

        # Sanity: TP must be in profit direction
        if side == "long" and tp <= row.close:
            return None
        if side == "short" and tp >= row.close:
            return None

        return {
            "action": "open",
            "side": side,
            "stop": float(stop), "tp": float(tp),
            "tag": f"MR_{side}",
            "extras": {"init_stop": float(stop)},
        }

    return strat

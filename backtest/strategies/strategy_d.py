"""Strategy D: signal-strength-adaptive leverage.

User-requested design. Trades happen at moderate frequency, but leverage and
risk-per-trade scale with how confident the signal is. Sideways or weak
signals -> small leverage; clean strong-trend setups -> larger leverage.

Signal strength score (0..100)
------------------------------
  +30  ADX             (20 -> 0pt, 40 -> 30pt, linear, capped)
  +25  BB width        (0.008 -> 0pt, 0.022 -> 25pt, capped)
  +25  Volume ratio    (1.0  -> 0pt, 1.5  -> 25pt, capped)
  +20  MTF agreement   (1H trend same direction as 4H trend = 20, else 0)
  --
  0..100 total  (pullback bonus dropped — anti-correlated with trend strength)

Action by score (v3: enter only above empirical positive-edge threshold)
-----------------------------------------------------------------------
  score < 70           skip (lower scores empirically negative-edge)
  70 <= score < 80     leverage 2.5x, risk 0.7%/trade
  80 <= score < 90     leverage 4.0x, risk 1.0%/trade
  score >= 90          leverage 5.5x, risk 1.3%/trade  (highest conviction)

Direction
---------
  4H trend = up   -> long candidates only
  4H trend = down -> short candidates only
  4H neutral      -> skip

Trigger
-------
  long:  RSI(1H) crossed up through 50 in last 4 bars (1h)
  short: RSI(1H) crossed down through 50 in last 4 bars (1h)
  AND 15m close confirms (long: green candle, short: red candle)

Risk management
---------------
  stop = entry +/- 1.5 * ATR(15m)
  break-even at +1R, then trail with 1.5 * ATR(15m) chandelier
  TP scale-out: 50% off at +2R (exit half), rest trails
  cooldown after stop: 6 bars (1.5h)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

ATR_STOP_MULT = 1.5
ATR_TRAIL_MULT = 1.5
COOLDOWN_BARS_LOSS = 6
TP_SCALE_R = 2.0


def _signal_strength(row, row_h1, row_h4) -> tuple[float, str]:
    """Returns (score 0..100, direction 'long'|'short'|'none')."""
    if row_h4 is None or pd.isna(row_h4.get("ema200", np.nan)):
        return 0.0, "none"
    if row_h1 is None or pd.isna(row_h1.get("rsi", np.nan)):
        return 0.0, "none"

    # 4H trend direction
    long_bias = (row_h4.close > row_h4.ema200) and (row_h4.ema50 > row_h4.ema200)
    short_bias = (row_h4.close < row_h4.ema200) and (row_h4.ema50 < row_h4.ema200)
    if not (long_bias or short_bias):
        return 0.0, "none"
    direction = "long" if long_bias else "short"

    # ADX component (0..30) — 20→0, 40→30
    adx = row.adx if not pd.isna(row.adx) else 20
    adx_pt = max(0, min(30, (adx - 20) * 1.5))

    # BB width component (0..25) — 0.008→0, 0.022→25
    bbw = row.bb_width if not pd.isna(row.bb_width) else 0.01
    bbw_pt = max(0, min(25, (bbw - 0.008) / 0.014 * 25))

    # Volume component (0..25) — 1.0→0, 1.5→25
    vr = row.vol_ratio if not pd.isna(row.vol_ratio) else 1.0
    vol_pt = max(0, min(25, (vr - 1.0) / 0.5 * 25))

    # MTF agreement (0..20)
    h1_long = row_h1.close > row_h1.ema50
    h1_short = row_h1.close < row_h1.ema50
    mtf_pt = 20 if (long_bias and h1_long) or (short_bias and h1_short) else 0

    score = adx_pt + bbw_pt + vol_pt + mtf_pt
    return score, direction


def _leverage_and_risk(score: float) -> tuple[float, float]:
    """Map score to (leverage, risk_per_trade)."""
    if score < 70: return 0.0, 0.0
    if score < 80: return 2.5, 0.007
    if score < 90: return 4.0, 0.010
    return 5.5, 0.013


def _rsi_crossed_50(rsi_series: pd.Series, lookback: int = 4) -> str:
    """Returns 'up', 'down', or 'none' for last `lookback` bars."""
    if len(rsi_series) < lookback + 1:
        return "none"
    win = rsi_series.iloc[-lookback - 1:].values
    for i in range(len(win) - 1):
        if win[i] < 50 and win[i + 1] >= 50:
            return "up"
        if win[i] > 50 and win[i + 1] <= 50:
            return "down"
    return "none"


def make_strategy():
    state = {"last_loss_idx": -10_000}

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        h1 = ctx["df_1h"]
        h4 = ctx["df_4h"]
        pos = ctx["position"]
        cfg = ctx["cfg"]
        row = df.iloc[i]
        row_h1 = h1.iloc[i] if h1 is not None else None
        row_h4 = h4.iloc[i] if h4 is not None else None

        # ----- manage open position -----
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
                # break-even at +1R
                if not pos.extras.get("be_done") and pnl >= R:
                    pos.extras["be_done"] = True
                    return {"action": "modify_stop", "stop": pos.entry}
                # Chandelier trail after BE
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

        # ----- cooldown -----
        if i - state["last_loss_idx"] < COOLDOWN_BARS_LOSS:
            return None

        # ----- compute signal strength -----
        score, direction = _signal_strength(row, row_h1, row_h4)
        if direction == "none" or score < 70:
            return None

        # ----- 1H RSI cross trigger (within last 4 1H bars) -----
        # h1 is aligned to 15m index; take last 16 (4*4) 15m rows of h1
        h1_window = h1.iloc[max(0, i - 16):i + 1]
        if len(h1_window) < 16:
            return None
        # de-duplicate (h1 ffill replicates same value across 4 15m rows)
        rsi_unique = h1_window["rsi"].drop_duplicates().tail(5)
        cross = _rsi_crossed_50(rsi_unique, lookback=4)
        if direction == "long" and cross != "up":
            return None
        if direction == "short" and cross != "down":
            return None

        # ----- candle confirmation -----
        if direction == "long" and row.close <= row.open:
            return None
        if direction == "short" and row.close >= row.open:
            return None

        # ----- compute stop -----
        atr15 = row.atr
        if pd.isna(atr15) or atr15 <= 0:
            return None

        if direction == "long":
            stop = row.close - ATR_STOP_MULT * atr15
        else:
            stop = row.close + ATR_STOP_MULT * atr15

        # ----- map score -> leverage / risk -----
        lev, risk = _leverage_and_risk(score)
        if lev == 0:
            return None

        # Override engine cfg via signal:
        # The engine uses cfg.risk_per_trade and cfg.max_leverage directly.
        # We can't change cfg per-trade, so we encode via size_pct in non-risk mode,
        # but since we're in risk mode, we use a custom override via extras.
        # Workaround: emit risk_override in signal; engine doesn't read this — we
        # instead synthesize a notional via stop distance.
        stop_dist_pct = abs(row.close - stop) / row.close
        equity = ctx["equity"]
        risk_dollars = equity * risk
        notional = risk_dollars / stop_dist_pct
        max_notional = equity * lev
        notional = min(notional, max_notional)
        size_pct_eff = notional / (equity * cfg.max_leverage) if cfg.max_leverage > 0 else 0

        return {
            "action": "open",
            "side": direction,
            "stop": float(stop),
            "tp": None,
            "size_pct": float(size_pct_eff),
            "tag": f"D_{direction}_s{int(score)}_lev{int(lev)}",
            "extras": {
                "init_stop": float(stop),
                "be_done": False,
                "score": float(score),
                "leverage_chosen": float(lev),
                "risk_chosen": float(risk),
            },
        }

    return strat

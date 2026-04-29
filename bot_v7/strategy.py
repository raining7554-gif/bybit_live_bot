"""Strategy D wired for live: signal-strength score + dynamic leverage decision.

Reuses indicator/score logic from `backtest.indicators` and
`backtest.strategies.strategy_d` to guarantee live = backtest.
"""
from __future__ import annotations
from typing import Optional
import pandas as pd

from . import config as cfg
from backtest.indicators import add_all_15m, add_basic_1h, add_basic_4h
from backtest.strategies.strategy_d import (
    _signal_strength, _rsi_crossed_50,
    ATR_STOP_MULT, ATR_TRAIL_MULT,
)
from backtest.strategies.strategy_mr import _check_signal as _mr_check_signal
from backtest.strategies.strategy_mr import (
    ATR_STOP_MULT as MR_ATR_STOP, LEV as MR_LEV,
)


def _leverage_for_score(score: float) -> float:
    """v7-3tier map: 5x / 7x / 10x. Sub-70 scores skip entirely."""
    if score < cfg.ENTRY_MIN_SCORE:  return 0.0           # < 70 → skip
    if score < cfg.SCORE_TIER_1:     return cfg.LEV_TIER_BASE   # 70..79
    if score < cfg.SCORE_TIER_2:     return cfg.LEV_TIER_MID    # 80..89
    return cfg.LEV_TIER_HIGH                                    # 90+


def compute_indicators(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                       df_4h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add all required columns. Caller passes raw OHLCV from exchange."""
    return add_all_15m(df_15m), add_basic_1h(df_1h), add_basic_4h(df_4h)


def evaluate_entry(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                   df_4h: pd.DataFrame) -> Optional[dict]:
    """Returns entry signal dict or None.

    Signal dict:
      {"side": "Buy"|"Sell", "score": float, "leverage": float,
       "stop_price": float, "entry_price": float, "atr_15m": float}
    """
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return None

    row    = df_15m.iloc[-1]
    row_h1 = df_1h.iloc[-1]
    row_h4 = df_4h.iloc[-1]

    score, direction = _signal_strength(row, row_h1, row_h4)
    if direction == "none" or score < cfg.ENTRY_MIN_SCORE:
        return None

    # 1H RSI cross 50 within last 4 1H bars
    rsi_recent = df_1h["rsi"].tail(5)
    cross = _rsi_crossed_50(rsi_recent, lookback=4)
    if direction == "long" and cross != "up":
        return None
    if direction == "short" and cross != "down":
        return None

    # 15m candle confirmation
    if direction == "long" and row.close <= row.open:
        return None
    if direction == "short" and row.close >= row.open:
        return None

    atr = row.atr
    if pd.isna(atr) or atr <= 0:
        return None

    if direction == "long":
        side = "Buy"
        stop = row.close - ATR_STOP_MULT * atr
    else:
        side = "Sell"
        stop = row.close + ATR_STOP_MULT * atr

    lev = _leverage_for_score(score)
    if lev <= 0:
        return None

    return {
        "side":        side,
        "score":       float(score),
        "leverage":    float(lev),
        "stop_price":  float(stop),
        "entry_price": float(row.close),
        "atr_15m":     float(atr),
    }


def evaluate_mr_entry(df_15m: pd.DataFrame, df_4h: pd.DataFrame) -> Optional[dict]:
    """Mean-reversion (MR) entry: oversold/overbought BB + chop ADX.

    Fires when D is silent — different alpha for sideways markets.
    Returns same-shape signal dict as evaluate_entry (for unified handling).
    """
    if len(df_15m) < 60:
        return None
    row = df_15m.iloc[-1]
    row_h4 = df_4h.iloc[-1] if df_4h is not None and len(df_4h) > 0 else None

    side, reason = _mr_check_signal(row, row_h4)
    if side == "none":
        return None

    atr = row.atr
    if pd.isna(atr) or atr <= 0:
        return None

    if side == "long":
        order_side = "Buy"
        stop = row.close - MR_ATR_STOP * atr
        tp = row.bb_mid
        if tp <= row.close:
            return None
    else:
        order_side = "Sell"
        stop = row.close + MR_ATR_STOP * atr
        tp = row.bb_mid
        if tp >= row.close:
            return None

    return {
        "side":        order_side,
        "score":       0.0,           # MR doesn't use D's score
        "leverage":    float(MR_LEV),
        "stop_price":  float(stop),
        "tp_price":    float(tp),
        "entry_price": float(row.close),
        "atr_15m":     float(atr),
        "tag":         f"MR_{side}",
        "mr":          True,
    }


def evaluate_position_management(pos: dict, atr_15m: float,
                                 last_high: float, last_low: float
                                 ) -> Optional[float]:
    """Returns new stop price if it should be tightened, else None.

    pos must contain: side ('Buy'/'Sell'), entry, current_stop, init_stop, be_done
    """
    side = pos["side"]
    entry = pos["entry"]
    init_stop = pos["init_stop"]
    cur_stop = pos["current_stop"]
    R = abs(entry - init_stop)
    if R <= 0 or atr_15m <= 0:
        return None

    if side == "Buy":
        # Break-even at +1R
        if not pos.get("be_done") and (last_high - entry) >= R:
            new_stop = entry
            if new_stop > cur_stop:
                pos["be_done"] = True
                return new_stop
        # Chandelier trail after BE
        if pos.get("be_done"):
            cand = last_high - ATR_TRAIL_MULT * atr_15m
            if cand > cur_stop:
                return cand
    else:  # Sell
        if not pos.get("be_done") and (entry - last_low) >= R:
            new_stop = entry
            if new_stop < cur_stop:
                pos["be_done"] = True
                return new_stop
        if pos.get("be_done"):
            cand = last_low + ATR_TRAIL_MULT * atr_15m
            if cand < cur_stop:
                return cand
    return None


def calc_qty(equity: float, leverage: float, price: float, symbol: str) -> float:
    """Margin-based sizing: notional = equity × MARGIN_PCT × leverage."""
    if equity <= 0 or price <= 0 or leverage <= 0:
        return 0.0
    margin = equity * cfg.MARGIN_PCT * cfg.CAPITAL_FRACTION
    notional = margin * leverage
    qty = notional / price
    decimals = cfg.QTY_DECIMALS.get(symbol, 2)
    qty = round(qty, decimals)
    if qty * price < 5.0:  # Bybit min order $5
        return 0.0
    return qty

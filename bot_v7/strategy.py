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
    _signal_strength, tier_for_score,
    ATR_STOP_MULT, ATR_TRAIL_MULT,
)
from backtest.strategies.strategy_mr import _check_signal as _mr_check_signal
from backtest.strategies.strategy_mr import (
    ATR_STOP_MULT as MR_ATR_STOP, LEV as MR_LEV,
)


def _leverage_for_score(score: float) -> float:
    """v8 5-tier map: 3x / 5x / 10x / 15x / 20x. Threshold 55."""
    if score < cfg.ENTRY_MIN_SCORE:   return 0.0            # < 55 → skip
    if score < cfg.SCORE_TIER_MICRO:  return cfg.LEV_TIER_MICRO  # 55..59
    if score < cfg.SCORE_TIER_PROBE:  return cfg.LEV_TIER_PROBE  # 60..69
    if score < cfg.SCORE_TIER_BASE:   return cfg.LEV_TIER_BASE   # 70..79
    if score < cfg.SCORE_TIER_MID:    return cfg.LEV_TIER_MID    # 80..89
    return cfg.LEV_TIER_HIGH                                     # 90+


def _tp_margin_for_tier(tier: str):
    """Returns the margin-% TP target for given tier, or None for trail-only."""
    return {
        "micro": cfg.TP_MARGIN_MICRO,
        "probe": cfg.TP_MARGIN_PROBE,
        "base":  cfg.TP_MARGIN_BASE,
        "mid":   cfg.TP1_MARGIN_MID,    # partial TP1
        "high":  cfg.TP_MARGIN_HIGH,    # None → trail only
    }.get(tier)


def _margin_pct_for_tier(tier: str) -> float:
    """v9 per-tier differential margin (Option C aggressive)."""
    return {
        "micro": cfg.MARGIN_PCT_MICRO,
        "probe": cfg.MARGIN_PCT_PROBE,
        "base":  cfg.MARGIN_PCT_BASE,
        "mid":   cfg.MARGIN_PCT_MID,
        "high":  cfg.MARGIN_PCT_HIGH,
        "mr":    cfg.MARGIN_PCT_MR,
    }.get(tier, cfg.MARGIN_PCT_BASE)


def _trail_mult_for_tier(tier: str) -> float:
    """v9 per-tier ATR trail multiplier — wider for high-conviction tiers."""
    if tier == "high": return cfg.TRAIL_ATR_HIGH
    if tier == "mid":  return cfg.TRAIL_ATR_MID
    return cfg.TRAIL_ATR_DEFAULT


def compute_indicators(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                       df_4h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add all required columns. Caller passes raw OHLCV from exchange."""
    return add_all_15m(df_15m), add_basic_1h(df_1h), add_basic_4h(df_4h)


def evaluate_entry(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                   df_4h: pd.DataFrame) -> Optional[dict]:
    """v8 entry. RSI directional check REMOVED. Score >= 55 + 4H bias (EMA50)
    + 15m candle alignment.
    """
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return None

    row    = df_15m.iloc[-1]
    row_h1 = df_1h.iloc[-1]
    row_h4 = df_4h.iloc[-1]

    score, direction = _signal_strength(row, row_h1, row_h4)
    if direction == "none" or score < cfg.ENTRY_MIN_SCORE:
        return None

    # v8: RSI directional check REMOVED entirely

    # 15m candle confirmation (kept — small filter)
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

    tier = tier_for_score(score)
    tp_margin = _tp_margin_for_tier(tier)

    return {
        "side":         side,
        "score":        float(score),
        "leverage":     float(lev),
        "stop_price":   float(stop),
        "entry_price":  float(row.close),
        "atr_15m":      float(atr),
        "tier":         tier,
        "tp_margin":    tp_margin,         # None for high tier
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


def evaluate_position_management(pos: dict, atr_15m: float, current_price: float,
                                 last_high: float, last_low: float) -> Optional[dict]:
    """v8 tier-aware exit logic.

    Returns one of:
      None                                  → no action
      {"action": "close", "reason": "tp"}   → fixed TP hit (micro/probe/base)
      {"action": "scale_out", "ratio": 0.5} → mid tier TP1 partial
      {"action": "modify_stop", "stop": x}  → BE move or trail update
    """
    side = pos["side"]
    entry = pos["entry"]
    leverage = pos.get("leverage", 1.0)
    tier = pos.get("tier", "high")
    tp_margin = pos.get("tp_margin")
    init_stop = pos["init_stop"]
    cur_stop = pos["current_stop"]
    R = abs(entry - init_stop)
    if R <= 0:
        return None

    # Compute current margin gain (= price gain × leverage)
    if side == "Buy":
        price_chg = (current_price - entry) / entry
    else:
        price_chg = (entry - current_price) / entry
    margin_pct = price_chg * leverage

    # ---- Fixed-TP tiers: full close at target ----
    if tier in ("micro", "probe", "base") and tp_margin is not None:
        if margin_pct >= tp_margin:
            return {"action": "close", "reason": "fixed_tp"}
        return None

    # ---- Mid tier: TP1 partial 50% then BE+trail rest ----
    if tier == "mid":
        if not pos.get("scale_done") and tp_margin is not None and margin_pct >= tp_margin:
            return {"action": "scale_out", "ratio": 0.5}
        if pos.get("scale_done"):
            trail_mult = _trail_mult_for_tier(tier)
            return _be_then_trail(pos, side, entry, cur_stop, R, atr_15m,
                                  last_high, last_low, trail_mult)
        return None

    # ---- High tier: BE @ +1R then chandelier (no fixed TP) ----
    if tier == "high":
        trail_mult = _trail_mult_for_tier(tier)
        return _be_then_trail(pos, side, entry, cur_stop, R, atr_15m,
                              last_high, last_low, trail_mult)

    return None


def _be_then_trail(pos, side, entry, cur_stop, R, atr_15m, last_high, last_low,
                   trail_mult: float = 1.5):
    """v9: trail_mult is tier-aware (mid 2.5, high 3.0)."""
    if atr_15m <= 0:
        return None
    if side == "Buy":
        if not pos.get("be_done") and (last_high - entry) >= R:
            new_stop = entry
            if new_stop > cur_stop:
                pos["be_done"] = True
                return {"action": "modify_stop", "stop": new_stop}
        if pos.get("be_done"):
            cand = last_high - trail_mult * atr_15m
            if cand > cur_stop:
                return {"action": "modify_stop", "stop": cand}
    else:
        if not pos.get("be_done") and (entry - last_low) >= R:
            new_stop = entry
            if new_stop < cur_stop:
                pos["be_done"] = True
                return {"action": "modify_stop", "stop": new_stop}
        if pos.get("be_done"):
            cand = last_low + trail_mult * atr_15m
            if cand < cur_stop:
                return {"action": "modify_stop", "stop": cand}
    return None


def calc_qty(equity: float, leverage: float, price: float, symbol: str,
             tier: str = "base", score: float | None = None,
             active_margin_used: float = 0.0) -> tuple[float, float]:
    """v13 sizing: 점수 기반 + 전체 마진 글로벌 캡.

    공식:
        margin_pct = tier_margin × (score/100)^SCORE_EXP
        margin_pct = min(margin_pct, MAX_TOTAL_MARGIN - active_margin_used)
        notional = equity × margin_pct × leverage

    Returns:
        (qty, margin_pct) — 둘 다 0이면 진입 skip.

    이전 v12 (1/N 분할) 와 차이:
      - 단일 신호 시 full tier 마진 사용 → 사이즈 약 5배 ↑
      - 동시 진입 시 글로벌 캡으로 총 노출 제한
    """
    if equity <= 0 or price <= 0 or leverage <= 0:
        return 0.0, 0.0

    base_margin = _margin_pct_for_tier(tier)
    # 점수 비례 미세조정 (None이면 1.0 = full tier margin, MR 등 score 없는 신호용)
    if score and score > 0:
        score_factor = max(0.0, min(1.0, (score / 100.0) ** cfg.SCORE_EXP))
    else:
        score_factor = 1.0
    desired_margin = base_margin * score_factor

    # 글로벌 캡 적용 — 다른 활성 포지션이 차지한 마진 차감
    available = max(0.0, cfg.MAX_TOTAL_MARGIN - active_margin_used)
    margin_pct = min(desired_margin, available)
    if margin_pct < 0.05:
        return 0.0, 0.0  # 5% 미만이면 의미 없음 → skip

    margin = equity * margin_pct * cfg.CAPITAL_FRACTION
    notional = margin * leverage
    qty = notional / price
    decimals = cfg.QTY_DECIMALS.get(symbol, 2)
    qty = round(qty, decimals)
    if qty * price < 5.0:
        return 0.0, 0.0
    return qty, margin_pct

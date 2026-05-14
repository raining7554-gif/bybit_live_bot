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
# v5.0 MR 강화판
from backtest.strategies.strategy_mr_v5 import (
    _check_signal_v5 as _mr_check_signal_v5,
    tier_for_score as _mr_tier_for_score,
    SCORE_MIN as _MR_SCORE_MIN,
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
                   df_4h: pd.DataFrame,
                   funding_8h_pct: float | None = None,
                   funding_24h_ago: float | None = None,
                   cross_agree: float | None = None,
                   oi_change_4h: float | None = None,
                   price_change_4h: float | None = None,
                   news_sentiment: float | None = None) -> Optional[dict]:
    """v15 entry. 10-component score (4 base + 6 multipliers).

    multipliers: HTF ADX, funding sanity, funding trend, cross-asset,
                 volatility regime, OI confirmation.
    """
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return None

    row    = df_15m.iloc[-1]
    row_h1 = df_1h.iloc[-1]
    row_h4 = df_4h.iloc[-1]

    score, direction = _signal_strength(
        row, row_h1, row_h4,
        funding_8h_pct=funding_8h_pct,
        funding_24h_ago=funding_24h_ago,
        cross_agree=cross_agree,
        oi_change_4h=oi_change_4h,
        price_change_4h=price_change_4h,
        news_sentiment=news_sentiment,
    )
    if direction == "none" or score < cfg.ENTRY_MIN_SCORE:
        return None

    # v6.28: 점수 ≥ 70 (base/mid/high) 는 데이터상 패자 (50건 분석 -$94).
    # 점수 역상관 (-5.3) + server_stop 56% → 추세 끝물 진입 패턴.
    # 가설: 강한 D 신호 = 추세 극단 = 평균회귀 임박 → 반대 매매.
    # 1~2주 라이브 검증, 데이터 안 좋으면 되돌림.
    inverse_applied = False
    if score >= cfg.D_INVERSE_THRESHOLD:
        direction = "short" if direction == "long" else "long"
        inverse_applied = True

    # 15m candle confirmation (kept — small filter)
    # v6.28: 반대매매시 캔들 방향 체크도 반대로
    if not inverse_applied:
        if direction == "long" and row.close <= row.open:
            return None
        if direction == "short" and row.close >= row.open:
            return None
    # 반대매매면 캔들 방향 체크 스킵 (추세 끝물 잡는 거라 캔들 반전 기다리지 않음)

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
        "tag":          "D_INV" if inverse_applied else "D",   # v6.28 트래킹
        "inverse":      inverse_applied,
    }


def evaluate_mr_entry(df_15m: pd.DataFrame, df_4h: pd.DataFrame) -> Optional[dict]:
    """v5.0 Mean-reversion entry — score 기반 MR primary 전략.

    BB 극단 + RSI 극단 + 거래량 스파이크 + 반전 캔들 = MR 신호.
    score 50+ 통과시 진입. score 별 tier 사이즈.
    """
    if len(df_15m) < 60:
        return None
    row = df_15m.iloc[-1]
    row_h4 = df_4h.iloc[-1] if df_4h is not None and len(df_4h) > 0 else None

    # v5: 점수 + side 한 번에 계산
    side, reason, score = _mr_check_signal_v5(row, row_h4)
    if side == "none":
        return None
    if score < _MR_SCORE_MIN:
        return None

    atr = row.atr
    if pd.isna(atr) or atr <= 0:
        return None

    tier_label, tier_margin = _mr_tier_for_score(score)
    if tier_label == "skip":
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
        "score":       float(score),
        "leverage":    float(MR_LEV),
        "stop_price":  float(stop),
        "tp_price":    float(tp),
        "tier":        f"mr_{tier_label}",
        "mr_tier_margin": float(tier_margin),  # v5 tier 별 마진
        "entry_price": float(row.close),
        "atr_15m":     float(atr),
        "tag":         f"MR_{side}",
        "mr":          True,
    }


def evaluate_position_management(pos: dict, atr_15m: float, current_price: float,
                                 last_high: float, last_low: float) -> Optional[dict]:
    """v8 tier-aware exit logic.

    v6.32: mid/high tier 2단계 분할 익절 + dynamic trail.

    Returns one of:
      None                                  → no action
      {"action": "close", "reason": "tp"}   → fixed TP hit (micro/probe/base)
      {"action": "scale_out", "ratio": x, "step": N} → 단계별 부분 청산
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

    # v6.32: peak margin 추적 (dynamic trail 용)
    peak = pos.get("peak_margin_pct", 0.0)
    if margin_pct > peak:
        pos["peak_margin_pct"] = margin_pct
        peak = margin_pct

    # ---- Fixed-TP tiers: full close at target ----
    if tier in ("micro", "probe", "base") and tp_margin is not None:
        if margin_pct >= tp_margin:
            return {"action": "close", "reason": "fixed_tp"}
        return None

    # ---- Mid tier: 2단계 분할 익절 (v6.32) ----
    if tier == "mid":
        step = pos.get("scale_step", 0)
        # TP1 +10% margin
        if step < 1 and margin_pct >= cfg.TP1_MARGIN_MID:
            return {"action": "scale_out", "ratio": cfg.TP1_RATIO_MID, "step": 1,
                    "reason": f"mid_TP1 (+{cfg.TP1_MARGIN_MID*100:.0f}%)"}
        # TP2 +20% margin
        if step < 2 and margin_pct >= cfg.TP2_MARGIN_MID:
            # remaining = 0.70 after TP1, TP2 close 30% of original = 30/70 = 0.4286 of current
            rem_ratio = cfg.TP2_RATIO_MID / max(0.01, 1 - cfg.TP1_RATIO_MID)
            return {"action": "scale_out", "ratio": rem_ratio, "step": 2,
                    "reason": f"mid_TP2 (+{cfg.TP2_MARGIN_MID*100:.0f}%)"}
        # 둘 다 끝나면 BE + trail
        if step >= 1:
            trail_mult = _trail_mult_for_tier(tier)
            return _be_then_trail(pos, side, entry, cur_stop, R, atr_15m,
                                  last_high, last_low, trail_mult)
        return None

    # ---- High tier: 2단계 분할 익절 + dynamic trail (v6.32) ----
    if tier == "high":
        step = pos.get("scale_step", 0)
        # TP1 +5% margin → 30% 청산
        if step < 1 and margin_pct >= cfg.TP1_MARGIN_HIGH:
            return {"action": "scale_out", "ratio": cfg.TP1_RATIO_HIGH, "step": 1,
                    "reason": f"high_TP1 (+{cfg.TP1_MARGIN_HIGH*100:.0f}%)"}
        # TP2 +15% margin → 30% 추가 청산
        if step < 2 and margin_pct >= cfg.TP2_MARGIN_HIGH:
            rem_ratio = cfg.TP2_RATIO_HIGH / max(0.01, 1 - cfg.TP1_RATIO_HIGH)
            return {"action": "scale_out", "ratio": rem_ratio, "step": 2,
                    "reason": f"high_TP2 (+{cfg.TP2_MARGIN_HIGH*100:.0f}%)"}
        # 분할 시작했으면 BE + dynamic trail, 아직 안 했으면 +1R 후 trail
        trail_mult = _high_trail_mult_dynamic(peak)
        return _be_then_trail(pos, side, entry, cur_stop, R, atr_15m,
                              last_high, last_low, trail_mult)

    return None


def _high_trail_mult_dynamic(peak_margin_pct: float) -> float:
    """v6.32: peak margin 이 클수록 trail 조여짐."""
    if not cfg.DYNAMIC_TRAIL_ENABLED:
        return cfg.TRAIL_ATR_HIGH
    if peak_margin_pct >= cfg.TRAIL_PEAK_VTIGHT_PCT:
        return cfg.TRAIL_ATR_HIGH_VTIGHT
    if peak_margin_pct >= cfg.TRAIL_PEAK_TIGHT_PCT:
        return cfg.TRAIL_ATR_HIGH_TIGHT
    return cfg.TRAIL_ATR_HIGH


def _be_then_trail(pos, side, entry, cur_stop, R, atr_15m, last_high, last_low,
                   trail_mult: float = 1.5):
    """v9: trail_mult is tier-aware (mid 2.5, high 3.0).

    v6.41 B: BE 가속 — peak_margin_pct ≥ 5% (high) / 7% (mid) 도달시 즉시 BE.
    기존 +1R 가격 기준은 큰 사이즈에서 너무 늦음.
    """
    if atr_15m <= 0:
        return None
    leverage = pos.get("leverage", 1.0)
    tier = pos.get("tier", "?")
    peak = pos.get("peak_margin_pct", 0.0)
    # v6.41 B: tier 별 BE 가속 임계치
    be_fast_threshold = None
    if tier == "high":
        be_fast_threshold = 0.05   # +5% margin
    elif tier == "mid":
        be_fast_threshold = 0.07   # +7% margin

    if side == "Buy":
        # 빠른 BE (margin 기준)
        if (not pos.get("be_done") and be_fast_threshold is not None
                and peak >= be_fast_threshold):
            new_stop = entry
            if new_stop > cur_stop:
                pos["be_done"] = True
                return {"action": "modify_stop", "stop": new_stop}
        # 기존 BE (R 기준)
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
        if (not pos.get("be_done") and be_fast_threshold is not None
                and peak >= be_fast_threshold):
            new_stop = entry
            if new_stop < cur_stop:
                pos["be_done"] = True
                return {"action": "modify_stop", "stop": new_stop}
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
             active_margin_used: float = 0.0,
             symbol_weight: float = 1.0) -> tuple[float, float]:
    """v15 sizing: 점수 + 심볼 가중치 + 글로벌 캡.

    공식:
        margin_pct = tier × (score/100)^SCORE_EXP × symbol_weight
        margin_pct = min(margin_pct, MAX_TOTAL_MARGIN - active_margin_used)

    symbol_weight (Tier 2 자동학습):
        1.0 = 중립
        > 1.0 = 잘 되는 심볼 boost
        < 1.0 = 부진한 심볼 축소
    """
    if equity <= 0 or price <= 0 or leverage <= 0:
        return 0.0, 0.0

    base_margin = _margin_pct_for_tier(tier)
    if score and score > 0:
        score_factor = max(0.0, min(1.0, (score / 100.0) ** cfg.SCORE_EXP))
    else:
        score_factor = 1.0
    # v15: 심볼별 자동 가중치 적용
    sw = max(0.3, min(1.5, symbol_weight))
    desired_margin = base_margin * score_factor * sw

    # 글로벌 캡 적용 — 다른 활성 포지션이 차지한 마진 차감
    available = max(0.0, cfg.MAX_TOTAL_MARGIN - active_margin_used)
    margin_pct = min(desired_margin, available)
    # v13.1: 10% 미만이면 의미없을 뿐 아니라 Bybit 수수료/IM 요구치
    # 못 맞춰서 110007 'ab not enough' 발생 가능 → 사전 차단
    if margin_pct < 0.10:
        return 0.0, 0.0

    margin = equity * margin_pct * cfg.CAPITAL_FRACTION
    notional = margin * leverage
    qty = notional / price
    decimals = cfg.QTY_DECIMALS.get(symbol, 2)
    qty = round(qty, decimals)
    if qty * price < 5.0:
        return 0.0, 0.0
    return qty, margin_pct

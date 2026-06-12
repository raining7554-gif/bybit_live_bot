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
    """v8 5-tier map: 3x / 5x / 10x / 15x / 20x. Threshold 55.

    v6.63: MAX_LEVERAGE_CAP 적용 (env 로 조정 가능. default 20).
    """
    if score < cfg.ENTRY_MIN_SCORE:   return 0.0            # < 55 → skip
    if score < cfg.SCORE_TIER_MICRO:  lev = cfg.LEV_TIER_MICRO  # 55..59
    elif score < cfg.SCORE_TIER_PROBE: lev = cfg.LEV_TIER_PROBE  # 60..69
    elif score < cfg.SCORE_TIER_BASE:  lev = cfg.LEV_TIER_BASE   # 70..79
    elif score < cfg.SCORE_TIER_MID:   lev = cfg.LEV_TIER_MID    # 80..89
    else:                              lev = cfg.LEV_TIER_HIGH   # 90+
    return min(lev, cfg.MAX_LEVERAGE_CAP)


def _tp_margin_for_tier(tier: str):
    """Returns the margin-% TP target for given tier, or None for trail-only."""
    return {
        "micro": cfg.TP_MARGIN_MICRO,
        "probe": cfg.TP_MARGIN_PROBE,
        "base":  cfg.TP_MARGIN_BASE,
        "mid":   cfg.TP1_MARGIN_MID,    # partial TP1
        "high":  cfg.TP_MARGIN_HIGH,    # None → trail only
        "swing": None,                  # v6.63 swing: trail only
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
        "swing": cfg.MARGIN_PCT_MID,    # v6.63 swing 은 mid 사이즈
    }.get(tier, cfg.MARGIN_PCT_BASE)


def _trail_mult_for_tier(tier: str) -> float:
    """v9 per-tier ATR trail multiplier — wider for high-conviction tiers."""
    if tier == "swing": return cfg.SWING_TRAIL_ATR_MULT  # v6.63 가장 넓은 trail
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
                   news_sentiment: float | None = None,
                   regime: dict | None = None) -> Optional[dict]:
    """v15 entry. 10-component score (4 base + 6 multipliers).

    multipliers: HTF ADX, funding sanity, funding trend, cross-asset,
                 volatility regime, OI confirmation.

    v6.63: regime 인자 추가. trending 레짐에서 D_INV 금지.
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

    # v6.28 → v6.63: D_INV 게이팅
    # 과거: 점수 65+ 모두 반전 → 트렌딩 시장에서 손실 폭주
    # 현재: regime gated. ranging 레짐 + 점수 매우 높음 (90+) 에서만 인버스
    # trending 레짐에선 절대 반전 X. mixed 도 보수적으로 X.
    inverse_applied = False
    if score >= cfg.D_INVERSE_THRESHOLD:
        # 기본 임계 도달 — 추가 게이트 통과시 인버스
        regime_ok = True
        if cfg.D_INVERSE_REGIME_GATED:
            regime_ok = False
            if regime and isinstance(regime, dict):
                reg_label = regime.get("regime", "")
                reg_conf = float(regime.get("confidence", 0))
                # ranging + 충분한 확신 + 매우 높은 점수
                if (reg_label == "ranging"
                        and reg_conf >= cfg.REGIME_GATE_MIN_CONF
                        and score >= cfg.D_INVERSE_RANGING_MIN):
                    regime_ok = True
        if regime_ok:
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
    # v6.68: PROBE_ONLY_ENTRIES — base/mid/high 신호 자체 skip (사용자 채택).
    # 데이터: base avg -$0.91, mid -$9.74 → 사이즈만 줄여도 음수. 아예 차단.
    # probe/micro 만 거래.
    if cfg.PROBE_ONLY_ENTRIES and tier in ("base", "mid", "high"):
        return None
    # v6.54: mid/high tier 캡 — 점수 80+ 도 base 사이즈로 제한
    # 데이터: mid 10건 -$98 / high 6건 -$74 (16건 -$172, 점수-승률 무상관)
    # 큰 사이즈 손실 차단. 진입 신호는 유지하되 base (10x/50%) 사이즈.
    # v6.63: trending 레짐 + 강한 시그널 = swing 후보 → 캡 우회 (별도 evaluate_swing 에서 처리)
    if cfg.TIER_CAP_ENABLED and tier in ("mid", "high"):
        tier = "base"
        lev = cfg.LEV_TIER_BASE
    # v6.66: PROBE_TIER_CAP — 한 단계 더 보수. base 도 probe 로 강등.
    # 30일 데이터: base/mid/high 모두 음수, probe/micro 만 양수.
    if cfg.PROBE_TIER_CAP and tier in ("base", "mid", "high"):
        tier = "probe"
        lev = cfg.LEV_TIER_PROBE
    # MAX_LEVERAGE_CAP 다시 적용 (env 가 더 엄격하면)
    lev = min(lev, cfg.MAX_LEVERAGE_CAP)
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


def evaluate_swing_entry(df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                         df_4h: pd.DataFrame,
                         regime: dict | None = None,
                         cross_agree: float | None = None,
                         funding_8h_pct: float | None = None) -> Optional[dict]:
    """v6.63 Swing 진입 — 4H 강한 추세 + 다중 심볼 컨플루언스 일치 시.

    조건 (모두 충족):
      - regime classify == 'trending' 이고 confidence >= REGIME_GATE_MIN_CONF
      - 4H ADX >= SWING_ADX_4H_MIN (기본 30)
      - cross_agree >= SWING_CROSS_AGREE_MIN (기본 0.7) — 다른 심볼도 같은 방향
      - 4H close 가 ema50 위/아래에서 명확
      - 15m base score >= 60 (entry timing)

    특성:
      - tier = 'swing' (mid 사이즈, tier cap 우회 옵션)
      - trail = SWING_TRAIL_ATR_MULT × ATR (기본 5×, 일반 trail 보다 넓음)
      - tp_margin = None (트레일만으로 청산)
      - inverse 절대 적용 안 됨
    """
    if not cfg.SWING_MODE_ENABLED:
        return None
    # v6.66: PROBE_TIER_CAP 활성 = 보수 모드. swing (15x) 도 차단.
    if cfg.PROBE_TIER_CAP:
        return None
    # v6.68: PROBE_ONLY_ENTRIES 활성 = base+ 차단. swing 도 당연히 차단.
    if cfg.PROBE_ONLY_ENTRIES:
        return None
    if len(df_15m) < 60 or len(df_1h) < 60 or len(df_4h) < 60:
        return None
    if not regime or not isinstance(regime, dict):
        return None
    if regime.get("regime") != "trending":
        return None
    if float(regime.get("confidence", 0)) < cfg.REGIME_GATE_MIN_CONF:
        return None

    row_h4 = df_4h.iloc[-1]
    adx_4h = float(getattr(row_h4, "adx", 0) or 0)
    if adx_4h < cfg.SWING_ADX_4H_MIN:
        return None

    if cross_agree is None or cross_agree < cfg.SWING_CROSS_AGREE_MIN:
        return None

    ema50_4h = float(getattr(row_h4, "ema50", 0) or 0)
    close_4h = float(row_h4.close)
    if ema50_4h <= 0:
        return None

    if close_4h > ema50_4h:
        direction = "long"
    elif close_4h < ema50_4h:
        direction = "short"
    else:
        return None

    row    = df_15m.iloc[-1]
    row_h1 = df_1h.iloc[-1]
    score, sig_dir = _signal_strength(
        row, row_h1, row_h4,
        funding_8h_pct=funding_8h_pct,
        cross_agree=cross_agree,
    )
    # 시그널 방향이 4H 방향과 다르면 진입 X (반대 매매는 swing 에서 절대 X)
    if sig_dir != direction:
        return None
    if score < 60:  # entry timing 필터
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

    # swing 은 mid 사이즈로 들어가되 tier cap 우회 옵션 (config)
    if cfg.SWING_TIER_CAP_BYPASS:
        tier = "swing"
        lev = cfg.LEV_TIER_MID
    else:
        tier = "base"
        lev = cfg.LEV_TIER_BASE

    return {
        "side":         side,
        "score":        float(score),
        "leverage":     float(lev),
        "stop_price":   float(stop),
        "entry_price":  float(row.close),
        "atr_15m":      float(atr),
        "tier":         tier,
        "tp_margin":    None,             # 트레일만으로 청산
        "tag":          "SWING",
        "inverse":      False,
        "swing":        True,
        "swing_trail_mult": cfg.SWING_TRAIL_ATR_MULT,
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

    # ---- Swing tier (v6.63): BE 후 매우 넓은 trail (4H 추세 라이딩) ----
    if tier == "swing":
        trail_mult = _trail_mult_for_tier(tier)  # SWING_TRAIL_ATR_MULT (5×)
        return _be_then_trail(pos, side, entry, cur_stop, R, atr_15m,
                              last_high, last_low, trail_mult)

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

"""Strategy MR v5 — Mean Reversion 강화판 (v4.x D 전략 폐기 후 primary).

v4.x 까지의 D (트렌드 추종) 데이터로 검증:
  - 31건 32% 승률 -$57
  - 점수 역상관 (높은 점수 = 더 많이 짐)
  - server_stop 68% (-2% 손절 자주 발동)
  → 트렌드 추종 자체가 안 맞음. MR (반전 매매) 로 전환.

MR v5 핵심:
  - 점수 시스템 0~100 (BB 극단 + RSI 극단 + 거래량 스파이크 + 반전 캔들)
  - 점수별 tier 사이즈 (작게 시작)
  - 단계별 TP (BB 중앙 → 반대 BB)
  - 시간 stop (4h 후 미반전시 exit)
  - 4H 강한 추세 시 진입 차단 (반대 방향만)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# ── 임계값 ───────────────────────────────────────────────────
# v6.23: 진입 빈도 늘리려 완화 (사용자: "비트봇도 조금 완화할까? 너무 안들어가긴 하더라")
ATR_STOP_MULT = 1.5
TIME_STOP_BARS = 16        # 16 × 15m = 4h 미반전시 강제 청산
ADX_CHOP_MAX = 32.0        # 30 → 32 (약간 더 추세 있어도 MR 허용)
RSI_OVERSOLD = 38.0        # 35 → 38 (덜 극단적이어도 OK)
RSI_OVERBOUGHT = 62.0      # 65 → 62
BB_POS_LOW = 0.20          # 0.15 → 0.20 (덜 극단적이어도 OK)
BB_POS_HIGH = 0.80         # 0.85 → 0.80
VOL_SPIKE_MIN = 1.3        # 1.5 → 1.3 (capitulation 조건 완화)
COOLDOWN_BARS_LOSS = 4
COOLDOWN_BARS_WIN = 2

# ── 점수 → 마진 tier (D 와 다른 보수적 사이즈) ───────────
# v6.25: mr_low (45-59) 가 데이터상 손실 주요 원인 (39건 -$34 분석)
# mr_med (60-79) 는 100% 승률 → mr_low 차단, mr_med+ 만 진입
SCORE_MIN = 55.0
TIER_THRESHOLDS = [
    (55.0, "low",    0.10),  # 55-59 → 10% margin (좁은 진입 영역)
    (60.0, "med",    0.20),  # 60-79 → 20%
    (80.0, "high",   0.35),  # 80+   → 35%
]


def _mr_score(row, row_h4) -> float:
    """0~100 MR 신호 강도. 극단성 + 반전 신뢰도 종합."""
    if pd.isna(row.get("adx", np.nan)) or pd.isna(row.get("bb_pos", np.nan)) \
       or pd.isna(row.get("rsi", np.nan)):
        return 0.0

    bb_pos = float(row.bb_pos)
    rsi = float(row.rsi)
    adx = float(row.adx)
    vol_ratio = float(row.get("vol_ratio", 1.0)) if not pd.isna(row.get("vol_ratio", np.nan)) else 1.0

    # 1) BB 극단성 (0~25): 0 또는 1.0 = 25, 0.5 = 0
    bb_extreme = abs(bb_pos - 0.5) * 2  # 0~1
    bb_pt = max(0, min(25, bb_extreme * 25))

    # 2) RSI 극단성 (0~25): 15/85 = 25, 50 = 0
    rsi_extreme = abs(rsi - 50) / 35  # 0~1
    rsi_pt = max(0, min(25, rsi_extreme * 25))

    # 3) 거래량 스파이크 (0~20): 1.0 = 0, 2.5+ = 20 (capitulation)
    vol_pt = max(0, min(20, (vol_ratio - 1.0) / 1.5 * 20))

    # 4) 반전 캔들 품질 (0~15)
    body = abs(row.close - row.open) if not pd.isna(row.close) else 0
    rng = row.high - row.low if not pd.isna(row.high) else 0
    body_ratio = body / rng if rng > 0 else 0
    candle_pt = max(0, min(15, body_ratio * 30))  # body 50% = 15pt

    # 5) 4H ADX 낮음 (0~15) — chop 환경에서 MR 잘 됨
    h4_adx = 25
    if row_h4 is not None and not pd.isna(row_h4.get("adx", np.nan)):
        h4_adx = float(row_h4.adx)
    if h4_adx <= 20:
        adx_pt = 15
    elif h4_adx <= 30:
        adx_pt = 15 - (h4_adx - 20) / 10 * 15
    else:
        adx_pt = 0

    base = bb_pt + rsi_pt + vol_pt + candle_pt + adx_pt
    return max(0, min(100, base))


def tier_for_score(score: float) -> tuple[str, float]:
    """점수 → (tier 라벨, 마진 비율)."""
    if score < SCORE_MIN:
        return "skip", 0.0
    chosen = TIER_THRESHOLDS[0]
    for t in TIER_THRESHOLDS:
        if score >= t[0]:
            chosen = t
    return chosen[1], chosen[2]


def _check_signal_v5(row, row_h4) -> tuple[str, str, float]:
    """Returns (side 'long'|'short'|'none', reason, score)."""
    score = _mr_score(row, row_h4)
    if score < SCORE_MIN:
        return "none", f"score {score:.0f} < {SCORE_MIN}", score

    if pd.isna(row.adx) or pd.isna(row.bb_pos) or pd.isna(row.rsi):
        return "none", "nan", 0.0

    if row.adx >= ADX_CHOP_MAX:
        return "none", f"adx {row.adx:.1f} > {ADX_CHOP_MAX} (trend, not chop)", score

    bullish = row.close > row.open
    bearish = row.close < row.open

    # 4H 강한 추세 차단 (반대 방향)
    h4_strong_up = False
    h4_strong_down = False
    if row_h4 is not None and not pd.isna(row_h4.get("ema200", np.nan)):
        h4_strong_up = (row_h4.close > row_h4.ema200) and (row_h4.ema50 > row_h4.ema200)
        h4_strong_down = (row_h4.close < row_h4.ema200) and (row_h4.ema50 < row_h4.ema200)

    # 거래량 스파이크 (점수에 이미 포함 — v6.26: hard gate 제거, score 만 신뢰)
    vol_ratio = float(row.get("vol_ratio", 1.0))

    # ── LONG ──
    if row.bb_pos < BB_POS_LOW and row.rsi < RSI_OVERSOLD and bullish:
        if h4_strong_down:
            return "none", "4H 강한 약세 — long 차단", score
        return "long", f"oversold + 반전 (vol {vol_ratio:.1f}x)", score

    # ── SHORT ──
    if row.bb_pos > BB_POS_HIGH and row.rsi > RSI_OVERBOUGHT and bearish:
        if h4_strong_up:
            return "none", "4H 강한 강세 — short 차단", score
        return "short", f"overbought + 반전 (vol {vol_ratio:.1f}x)", score

    return "none", "no extreme", score


# ── 레거시 호환 (기존 코드가 _check_signal 호출) ──────────
def _check_signal(row, row_h4) -> tuple[str, str]:
    side, reason, _ = _check_signal_v5(row, row_h4)
    return side, reason

"""Rule-based regime classifier (v6.0).

ADX/BB width 기반 trending/ranging/mixed 분류. AI 호출 없음.
초기엔 거래 결정에 미적용 — 분류 정확도부터 관측 (1~2주).

후속 단계:
  - trending → D 전략 우세
  - ranging → MR 전략 우세
  - mixed → MR primary + D 작은 사이즈
"""
from __future__ import annotations
from typing import Optional
import pandas as pd


# ── 임계치 ──────────────────────────────────────────────────────
ADX_TRENDING_4H = 25.0   # 4H ADX 이상 = 강한 추세
ADX_TRENDING_1H = 22.0   # 1H ADX 보조
ADX_RANGING    = 18.0    # 양 TF 모두 이하 = 약한 추세
BB_NARROW_PCT  = 0.70    # 1H BB width 가 20-bar median 의 70% 미만 = 좁음


def classify(df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> Optional[dict]:
    """현재 레짐 분류.

    Returns: {
        "regime":      "trending" | "ranging" | "mixed",
        "suggested":   "D" | "MR" | "MR",     # 권장 전략
        "confidence":  0.0~1.0,
        "adx_4h":      float,
        "adx_1h":      float,
        "bb_width_1h": float,                 # 현재 width
        "bb_width_med": float,                # 20-bar median
        "bb_ratio":    float,                 # 현재 / median
    }
    또는 None (데이터 부족).
    """
    if df_1h is None or df_4h is None:
        return None
    if len(df_1h) < 30 or len(df_4h) < 20:
        return None

    r4 = df_4h.iloc[-1]
    r1 = df_1h.iloc[-1]
    adx_4h = float(getattr(r4, "adx", 0) or 0)
    adx_1h = float(getattr(r1, "adx", 0) or 0)
    bb_w = float(getattr(r1, "bb_width", 0) or 0)
    if adx_4h <= 0 or adx_1h <= 0 or bb_w <= 0:
        return None

    # 1H BB width 의 최근 20-bar median 대비 현재 비율
    bb_series = df_1h["bb_width"].tail(20).dropna()
    bb_med = float(bb_series.median()) if len(bb_series) >= 10 else bb_w
    bb_ratio = bb_w / bb_med if bb_med > 0 else 1.0

    # ── 분류 ─────────────────────────────────────────────
    if adx_4h >= ADX_TRENDING_4H and adx_1h >= ADX_TRENDING_1H:
        regime = "trending"
        suggested = "D"
        # ADX 가 임계치에서 멀수록 confidence 높음
        excess = (adx_4h - ADX_TRENDING_4H) / 25.0   # 50 까지 → 1.0
        confidence = max(0.5, min(1.0, 0.5 + excess))
    elif adx_4h <= ADX_RANGING and adx_1h <= ADX_RANGING and bb_ratio < BB_NARROW_PCT:
        regime = "ranging"
        suggested = "MR"
        deficit = (ADX_RANGING - adx_4h) / ADX_RANGING
        narrow = (BB_NARROW_PCT - bb_ratio) / BB_NARROW_PCT
        confidence = max(0.5, min(1.0, 0.5 + (deficit + narrow) / 2))
    else:
        regime = "mixed"
        suggested = "MR"   # mixed 일 땐 MR 가 더 안전
        confidence = 0.4   # 낮은 신뢰도

    return {
        "regime":       regime,
        "suggested":    suggested,
        "confidence":   round(confidence, 2),
        "adx_4h":       round(adx_4h, 1),
        "adx_1h":       round(adx_1h, 1),
        "bb_width_1h":  round(bb_w, 5),
        "bb_width_med": round(bb_med, 5),
        "bb_ratio":     round(bb_ratio, 2),
    }


def format_regime_msg(per_symbol: dict[str, dict]) -> str:
    """심볼별 레짐 dict → 텔레그램 메시지."""
    if not per_symbol:
        return "🧭 레짐 분류 — 데이터 없음"
    lines = ["🧭 <b>심볼별 레짐 (룰베이스)</b>"]
    icon_map = {"trending": "🔥", "ranging": "💤", "mixed": "🌫"}
    for sym, r in per_symbol.items():
        if not r:
            lines.append(f"⚪ {sym}: 데이터 부족")
            continue
        icon = icon_map.get(r["regime"], "❓")
        lines.append(
            f"{icon} <b>{sym}</b>: {r['regime']} "
            f"(권장 {r['suggested']}, 신뢰 {int(r['confidence']*100)}%)\n"
            f"   ADX 4H={r['adx_4h']} 1H={r['adx_1h']} | "
            f"BB ratio={r['bb_ratio']}x"
        )
    lines.append("")
    lines.append("⚠️ 현재 거래 결정에 미적용 (관측 단계)")
    return "\n".join(lines)

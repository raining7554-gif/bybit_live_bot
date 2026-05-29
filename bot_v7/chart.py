"""v6.56 차트 생성 — 일목균형표 + 추세선 + 지지/저항 (matplotlib).

candles 입력 (최신순 list of dict: open/high/low/close), PNG bytes 반환.
KIS (KR/US) + Bybit (crypto) 공용 가능하나 각 봇이 자기 데이터 fetch 후 호출.
"""
from __future__ import annotations
import io
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # 서버 (no display)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np


def _ichimoku(highs, lows, closes):
    """일목균형표 계산. 입력은 오래된→최신 순서.

    Returns dict of arrays (NaN-padded to align with input length).
    """
    n = len(closes)
    tenkan = [np.nan] * n   # 전환선 (9)
    kijun = [np.nan] * n    # 기준선 (26)
    span_a = [np.nan] * n   # 선행스팬1
    span_b = [np.nan] * n   # 선행스팬2 (52)
    chikou = [np.nan] * n    # 후행스팬

    for i in range(n):
        if i >= 8:
            tenkan[i] = (max(highs[i-8:i+1]) + min(lows[i-8:i+1])) / 2
        if i >= 25:
            kijun[i] = (max(highs[i-25:i+1]) + min(lows[i-25:i+1])) / 2
        if i >= 51:
            span_b[i] = (max(highs[i-51:i+1]) + min(lows[i-51:i+1])) / 2
        if not np.isnan(tenkan[i]) and not np.isnan(kijun[i]):
            span_a[i] = (tenkan[i] + kijun[i]) / 2

    # 후행스팬 = 현재 종가를 26 뒤로 (그래프용은 26 앞 종가)
    for i in range(n):
        if i + 26 < n:
            chikou[i] = closes[i + 26]

    return {
        "tenkan": tenkan, "kijun": kijun,
        "span_a": span_a, "span_b": span_b, "chikou": chikou,
    }


def _find_pivots(values, window=5, kind="high"):
    """국소 고점/저점 인덱스 찾기."""
    pivots = []
    n = len(values)
    for i in range(window, n - window):
        seg = values[i-window:i+window+1]
        if kind == "high" and values[i] == max(seg):
            pivots.append(i)
        elif kind == "low" and values[i] == min(seg):
            pivots.append(i)
    return pivots


def make_chart(candles: list, title: str, is_crypto: bool = False,
               entry: float = 0, sl: float = 0, tp: float = 0) -> Optional[bytes]:
    """차트 PNG bytes 생성.

    candles: 최신순 (candles[0] = 오늘). open/high/low/close 키.
    v6.59: entry/sl/tp 지정시 수평선 그림.
    """
    if len(candles) < 30:
        return None

    # 오래된→최신 순서로 뒤집기 + 최근 120봉만
    data = list(reversed(candles[:120]))
    # v6.57: open 누락/0 이면 직전 종가로 fallback
    closes = [float(c["close"]) for c in data]
    opens = []
    for i, c in enumerate(data):
        o = float(c.get("open", 0) or 0)
        if o <= 0:
            o = closes[i-1] if i > 0 else closes[i]
        opens.append(o)
    highs = [float(c["high"]) for c in data]
    lows = [float(c["low"]) for c in data]
    n = len(closes)
    x = list(range(n))

    ich = _ichimoku(highs, lows, closes)

    fig, ax = plt.subplots(figsize=(12, 6), dpi=90)

    # ── 캔들 ─────────────────────────
    for i in range(n):
        color = "#26a69a" if closes[i] >= opens[i] else "#ef5350"
        # 심지
        ax.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.6, zorder=2)
        # 몸통
        body_low = min(opens[i], closes[i])
        body_h = abs(closes[i] - opens[i]) or (highs[i] - lows[i]) * 0.001
        ax.add_patch(plt.Rectangle((i - 0.3, body_low), 0.6, body_h,
                                    facecolor=color, edgecolor=color, zorder=3))

    # ── 일목 구름대 ──────────────────
    sa = np.array(ich["span_a"], dtype=float)
    sb = np.array(ich["span_b"], dtype=float)
    valid = ~(np.isnan(sa) | np.isnan(sb))
    ax.fill_between(x, sa, sb, where=(valid & (sa >= sb)),
                    facecolor="#26a69a", alpha=0.15, zorder=1)
    ax.fill_between(x, sa, sb, where=(valid & (sa < sb)),
                    facecolor="#ef5350", alpha=0.15, zorder=1)
    ax.plot(x, sa, color="#26a69a", linewidth=0.7, alpha=0.6, label="Senkou A")
    ax.plot(x, sb, color="#ef5350", linewidth=0.7, alpha=0.6, label="Senkou B")

    # ── 전환선/기준선 ─────────────────
    ax.plot(x, ich["tenkan"], color="#2962ff", linewidth=1.0, label="Tenkan(9)")
    ax.plot(x, ich["kijun"], color="#ff6d00", linewidth=1.0, label="Kijun(26)")

    # ── 추세선 (피봇 연결) ────────────
    ph = _find_pivots(highs, window=5, kind="high")
    pl = _find_pivots(lows, window=5, kind="low")
    if len(ph) >= 2:
        a, b = ph[-2], ph[-1]
        slope = (highs[b] - highs[a]) / (b - a) if b != a else 0
        y0 = highs[a] + slope * (0 - a)
        y1 = highs[a] + slope * (n - 1 - a)
        ax.plot([0, n-1], [y0, y1], color="#d50000", linewidth=1.2,
                linestyle="--", alpha=0.7, label="Resistance")
    if len(pl) >= 2:
        a, b = pl[-2], pl[-1]
        slope = (lows[b] - lows[a]) / (b - a) if b != a else 0
        y0 = lows[a] + slope * (0 - a)
        y1 = lows[a] + slope * (n - 1 - a)
        ax.plot([0, n-1], [y0, y1], color="#00c853", linewidth=1.2,
                linestyle="--", alpha=0.7, label="Support")

    # ── 지지/저항 수평선 (최근 고저) ──
    recent = closes[-20:]
    r_high = max(highs[-20:])
    r_low = min(lows[-20:])
    ax.axhline(r_high, color="#d50000", linewidth=0.5, alpha=0.4)
    ax.axhline(r_low, color="#00c853", linewidth=0.5, alpha=0.4)

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", fontsize=7, ncol=3)
    ax.grid(True, alpha=0.15)
    ax.set_xlim(-1, n)

    # v6.59: 진입/손절/익절 수평선
    if entry > 0:
        ax.axhline(entry, color="#424242", linewidth=1.3, linestyle="-", alpha=0.8)
        ax.annotate(f"Entry {entry:,.2f}", xy=(0, entry), fontsize=8,
                    color="#424242", fontweight="bold",
                    xytext=(2, 3), textcoords="offset points")
    if sl > 0:
        ax.axhline(sl, color="#d50000", linewidth=1.3, linestyle="-", alpha=0.8)
        ax.annotate(f"SL {sl:,.2f}", xy=(0, sl), fontsize=8,
                    color="#d50000", fontweight="bold",
                    xytext=(2, 3), textcoords="offset points")
    if tp > 0:
        ax.axhline(tp, color="#00c853", linewidth=1.3, linestyle="-", alpha=0.8)
        ax.annotate(f"TP {tp:,.2f}", xy=(0, tp), fontsize=8,
                    color="#00c853", fontweight="bold",
                    xytext=(2, 3), textcoords="offset points")

    # 현재가 표시
    cur = closes[-1]
    ax.annotate(f"{cur:,.2f}", xy=(n-1, cur), fontsize=9,
                color="black", fontweight="bold",
                xytext=(5, 0), textcoords="offset points", va="center")

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def chart_analysis(candles: list, ticker: str = "", is_crypto: bool = False,
                   entry: float = 0, sl: float = 0, tp: float = 0) -> str:
    """v6.58/6.59: 차트 해설 + 단기/장기 분석 + 손절/익절 R:R.

    범례 의미 + 일목 판정 + 단기/장기 현재가 위치 분석.
    entry/sl/tp 지정시 R:R 계산 포함.
    """
    if len(candles) < 30:
        return "데이터 부족"

    data = list(reversed(candles[:120]))
    closes = [float(c["close"]) for c in data]
    highs = [float(c["high"]) for c in data]
    lows = [float(c["low"]) for c in data]
    n = len(closes)
    cur = closes[-1]

    ich = _ichimoku(highs, lows, closes)
    tenkan = ich["tenkan"][-1]
    kijun = ich["kijun"][-1]
    span_a = ich["span_a"][-1]
    span_b = ich["span_b"][-1]

    def sma(vals, p):
        return sum(vals[-p:]) / p if len(vals) >= p else 0
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200) if n >= 200 else 0

    def fmt(p):
        if is_crypto or (ticker and ticker.isalpha()):
            return f"${p:,.2f}"
        return f"₩{p:,.0f}"

    lines = [f"📊 <b>{ticker} 분석</b>"]

    # ── 범례 설명 ──────────────────
    lines.append("\n<b>📖 차트 범례</b>")
    lines.append("🔵 Tenkan(9): 전환선 — 단기 추세")
    lines.append("🟠 Kijun(26): 기준선 — 중기 추세")
    lines.append("☁️ 구름대: 지지/저항 영역 (녹색=강세, 빨강=약세)")
    lines.append("🔴 Resistance: 저항 추세선 (고점 연결)")
    lines.append("🟢 Support: 지지 추세선 (저점 연결)")

    # ── 일목 종합 판정 ──────────────
    lines.append("\n<b>☁️ 일목균형표 판정</b>")
    # 구름 대비 위치
    if not (span_a != span_a or span_b != span_b):  # not NaN
        cloud_top = max(span_a, span_b)
        cloud_bot = min(span_a, span_b)
        if cur > cloud_top:
            lines.append(f"• 가격이 구름 <b>위</b> → 강세 ✅ (구름 상단 {fmt(cloud_top)} 지지)")
        elif cur < cloud_bot:
            lines.append(f"• 가격이 구름 <b>아래</b> → 약세 🔴 (구름 하단 {fmt(cloud_bot)} 저항)")
        else:
            lines.append(f"• 가격이 구름 <b>안</b> → 중립/방향 모색 ⚪")
    # 전환선 vs 기준선
    if tenkan == tenkan and kijun == kijun:
        if tenkan > kijun:
            lines.append(f"• 전환선이 기준선 위 → 단기 매수 우위 🟢")
        else:
            lines.append(f"• 전환선이 기준선 아래 → 단기 매도 우위 🔴")

    # ── 단기 분석 (전환선 / MA20) ────
    lines.append("\n<b>📈 단기 (수일~2주)</b>")
    if tenkan == tenkan:
        diff = (cur - tenkan) / tenkan * 100
        pos = "위" if cur > tenkan else "아래"
        lines.append(f"• 전환선 {fmt(tenkan)} {pos} ({diff:+.1f}%)")
    if ma20 > 0:
        diff = (cur - ma20) / ma20 * 100
        pos = "위" if cur > ma20 else "아래"
        emoji = "🟢" if cur > ma20 else "🔴"
        lines.append(f"• MA20 {fmt(ma20)} {pos} ({diff:+.1f}%) {emoji}")
    # 단기 모멘텀 (최근 5봉)
    if n >= 5:
        chg5 = (cur - closes[-5]) / closes[-5] * 100
        lines.append(f"• 최근 5봉 {chg5:+.1f}%")

    # ── 장기 분석 (기준선 / MA50,200 / 구름) ──
    lines.append("\n<b>📉 장기 (수주~수개월)</b>")
    if ma50 > 0:
        diff = (cur - ma50) / ma50 * 100
        pos = "위" if cur > ma50 else "아래"
        emoji = "🟢" if cur > ma50 else "🔴"
        lines.append(f"• MA50 {fmt(ma50)} {pos} ({diff:+.1f}%) {emoji}")
    if ma200 > 0:
        diff = (cur - ma200) / ma200 * 100
        pos = "위" if cur > ma200 else "아래"
        emoji = "🟢" if cur > ma200 else "🔴"
        lines.append(f"• MA200 {fmt(ma200)} {pos} ({diff:+.1f}%) {emoji}")
        # 정배열 판정
        if ma20 > ma50 > ma200:
            lines.append("• <b>정배열</b> (MA20 ↑ MA50 ↑ MA200) → 강한 상승추세 ✅")
        elif ma20 < ma50 < ma200:
            lines.append("• <b>역배열</b> (MA20 ↓ MA50 ↓ MA200) → 강한 하락추세 🔴")
        else:
            lines.append("• 혼조 배열 → 방향성 불명확 ⚪")

    # ── 종합 ──────────────────
    lines.append("\n<b>🎯 종합</b>")
    bull_signals = 0
    if ma20 > 0 and cur > ma20:
        bull_signals += 1
    if ma50 > 0 and cur > ma50:
        bull_signals += 1
    if tenkan == tenkan and cur > tenkan:
        bull_signals += 1
    if not (span_a != span_a) and cur > max(span_a, span_b):
        bull_signals += 1
    if bull_signals >= 3:
        lines.append("강세 우위 — 추세 추종 매수 관점")
    elif bull_signals <= 1:
        lines.append("약세 우위 — 반등 확인 전 관망")
    else:
        lines.append("중립 — 구름/MA 돌파 방향 확인 후 진입")

    # ── v6.60: 진입 타이밍 분석 ──────────
    # RSI, BB pos, MA20 거리 기반
    if n >= 20:
        var = sum((c - ma20) ** 2 for c in closes[-20:]) / 20
        std = var ** 0.5
        bb_up = ma20 + 2 * std
        bb_lo = ma20 - 2 * std
        bb_pos = (cur - bb_lo) / (bb_up - bb_lo) if bb_up > bb_lo else 0.5
        # RSI
        gains = [max(closes[i] - closes[i-1], 0) for i in range(n-14, n) if i > 0]
        losses = [max(closes[i-1] - closes[i], 0) for i in range(n-14, n) if i > 0]
        ag = sum(gains) / 14 if gains else 0
        al = sum(losses) / 14 if losses else 0
        rsi = 100 - 100 / (1 + ag / al) if al > 0 else 50
        ma20_dist = (cur - ma20) / ma20 * 100 if ma20 > 0 else 0

        lines.append("\n<b>⏱️ 진입 타이밍</b> (long 기준)")
        if rsi > 72:
            lines.append(f"• RSI {rsi:.0f} 과열 → 🔴 풀백 대기 (MA20 {fmt(ma20)} 근처)")
        elif rsi < 35:
            lines.append(f"• RSI {rsi:.0f} 과매도 → 반등 신호 확인 후 (위험)")
        elif ma20_dist > 6:
            lines.append(f"• 가격 MA20 대비 +{ma20_dist:.1f}% 확장 → 🟡 풀백 대기 권장")
        elif bull_signals >= 3 and 0 <= ma20_dist <= 3:
            lines.append(f"• 강세 + MA20 근접 ({ma20_dist:+.1f}%) → 🟢 진입 양호")
        elif bull_signals >= 3 and bb_pos < 0.4:
            lines.append(f"• 강세 + BB 하단 풀백 (pos {bb_pos:.2f}) → 🟢 좋은 진입점")
        elif bull_signals <= 1:
            lines.append(f"• 약세 구조 → ⚪ 진입 보류, 추세 전환 대기")
        else:
            lines.append(f"• 중립 (RSI {rsi:.0f}, MA20 {ma20_dist:+.1f}%) → 돌파 확인 후")

        # 이상적 진입 가격대 제안
        if bull_signals >= 2:
            ideal_low = ma20
            ideal_high = ma20 * 1.02
            lines.append(f"• 이상 진입대: {fmt(ideal_low)} ~ {fmt(ideal_high)} (MA20 부근)")

    # ── 손절/익절 R:R 분석 ──────────
    # ATR 계산 (자동 제안용)
    atr = 0
    if n >= 15:
        trs = []
        for i in range(n - 14, n):
            if i > 0:
                trs.append(max(highs[i] - lows[i],
                               abs(highs[i] - closes[i-1]),
                               abs(lows[i] - closes[i-1])))
        atr = sum(trs) / len(trs) if trs else 0

    if entry > 0 or sl > 0 or tp > 0:
        lines.append("\n<b>💰 손절/익절</b>")
        e = entry if entry > 0 else cur
        if entry > 0:
            lines.append(f"• 진입: {fmt(entry)}")
        if sl > 0:
            risk = (e - sl) / e * 100
            lines.append(f"• 손절: {fmt(sl)} ({risk:+.1f}%)")
        if tp > 0:
            reward = (tp - e) / e * 100
            lines.append(f"• 익절: {fmt(tp)} ({reward:+.1f}%)")
        if sl > 0 and tp > 0 and e != sl:
            rr = abs(tp - e) / abs(e - sl)
            rr_emoji = "✅" if rr >= 2 else "🟡" if rr >= 1.5 else "🔴"
            lines.append(f"• <b>R:R = 1:{rr:.1f}</b> {rr_emoji}")
            if rr < 1.5:
                lines.append("  ⚠️ R:R 낮음 — 익절 늘리거나 손절 좁히기 권장")
    elif atr > 0:
        # 자동 제안 (현재가 기준 long 가정)
        lines.append("\n<b>💡 자동 손절/익절 제안</b> (현재가 기준 long)")
        sug_sl = cur - 1.5 * atr
        sug_tp = cur + 3.0 * atr  # 2:1 R:R
        lines.append(f"• 손절 (−1.5×ATR): {fmt(sug_sl)} ({-1.5*atr/cur*100:.1f}%)")
        lines.append(f"• 익절 (+3×ATR): {fmt(sug_tp)} ({3*atr/cur*100:+.1f}%)")
        lines.append(f"• R:R = 1:2.0 ✅")
        lines.append(f"  <i>/chart {ticker} {cur:.0f} {sug_sl:.0f} {sug_tp:.0f} 로 라인 표시</i>")

    return "\n".join(lines)


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


def make_chart(candles: list, title: str, is_crypto: bool = False) -> Optional[bytes]:
    """차트 PNG bytes 생성.

    candles: 최신순 (candles[0] = 오늘). open/high/low/close 키.
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

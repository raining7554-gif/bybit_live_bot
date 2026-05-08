"""나스닥 스윙 전략 v1.0

진입 (일봉 기준):
  - 50일선 > 200일선 (장기 정배열)
  - 종가 > 20일선
  - RSI(14) 50~70 (모멘텀 + 과열 회피)
  - 당일 거래량 >= 20일 평균 × 1.3
  - 20일 고점 돌파 또는 20일선 되돌림 후 양봉

청산:
  - 하드 손절 -5%
  - 고점 대비 -10% 트레일링
  - 일봉 50MA 이탈
  - 패닉 방어: QQQ -2% 이상일 때 포지션 축소
"""
import kis_auth as api
from config import OS_STOP_LOSS, OS_TRAIL_DROP

# v11.1: 페이지네이션 + 거래소 fallback 적용된 통합 일봉 함수 사용.
# strategy_leveraged.py 의 함수가 BYMD 페이지네이션 + AMS/NYS/NAS fallback 처리.
from strategy_leveraged import get_overseas_daily as _get_overseas_daily_paginated


def get_overseas_daily(ticker: str, exchange: str, count: int = 200) -> list:
    """해외 일봉 조회 (페이지네이션 + 거래소 fallback).

    이전엔 단일 호출(~100건)만 해서 MA200 계산 실패. v11.1에서
    strategy_leveraged 의 페이지네이션 함수로 교체.
    """
    return _get_overseas_daily_paginated(ticker, exchange=exchange, count=count)


def _safe_float(v, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def get_overseas_current(ticker: str, exchange: str) -> dict:
    try:
        data = api.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
        )
        if data.get("rt_cd") == "0":
            o = data.get("output", {})
            # last 비어있으면 base / open 으로 fallback
            price = 0.0
            for key in ("last", "base", "open", "pre"):
                price = _safe_float(o.get(key))
                if price > 0:
                    break
            return {
                "price": price,
                "change_rate": _safe_float(o.get("rate")),
                "volume": int(_safe_float(o.get("tvol"))),
            }
    except Exception:
        pass
    return {}


def _ma(values, period):
    if len(values) < period:
        return 0.0
    return sum(values[:period]) / period


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(period):
        diff = closes[i] - closes[i + 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


# ═══════════════════════════════════════════════════════
# 시장 국면 (QQQ + VIX 근사)
# ═══════════════════════════════════════════════════════
def get_os_regime() -> dict:
    """QQQ 일봉으로 국면 판단"""
    try:
        candles = get_overseas_daily("QQQ", "NAS", count=210)
        if len(candles) < 50:
            return {"regime": "BULL", "qqq_ma50": 0, "qqq_ma200": 0}

        closes = [c["close"] for c in candles]
        ma50 = _ma(closes, 50)
        ma200 = _ma(closes, 200) if len(closes) >= 200 else ma50
        today = closes[0]

        if today > ma50 and ma50 > ma200:
            regime = "BULL"
        elif today < ma50 * 0.97:
            regime = "BEAR"
        else:
            regime = "SIDEWAYS"

        print(f"[OS_REGIME] {regime} QQQ={today:.2f} MA50={ma50:.2f} MA200={ma200:.2f}")
        return {"regime": regime, "qqq_ma50": ma50, "qqq_ma200": ma200, "qqq_price": today}
    except Exception as e:
        print(f"[OS_REGIME] 오류: {e}")
    return {"regime": "BULL", "qqq_ma50": 0, "qqq_ma200": 0}


def check_qqq_panic() -> bool:
    """당일 QQQ -2% 이상 하락 여부"""
    info = get_overseas_current("QQQ", "NAS")
    if not info:
        return False
    return info.get("change_rate", 0) <= -2.0


# ═══════════════════════════════════════════════════════
# 스윙 진입 조건
# ═══════════════════════════════════════════════════════
def check_os_entry(ticker: str, exchange: str, name: str = "") -> tuple:
    candles = get_overseas_daily(ticker, exchange, count=210)
    if len(candles) < 50:
        return False, "일봉 부족", {}

    closes = [c["close"] for c in candles]
    highs  = [c["high"] for c in candles]
    vols   = [c["volume"] for c in candles]

    ma20  = _ma(closes, 20)
    ma50  = _ma(closes, 50)
    ma200 = _ma(closes, 200) if len(closes) >= 200 else ma50
    rsi   = _rsi(closes)

    today_close = closes[0]
    today_vol   = vols[0]
    avg_vol20   = sum(vols[1:21]) / 20 if len(vols) >= 21 else sum(vols) / len(vols)
    high_20     = max(highs[1:21]) if len(highs) >= 21 else max(highs[1:])

    # v4.0: 14일 ATR% 계산 (변동성 사이징용)
    lows = [c["low"] for c in candles]
    atr_pct = 0.02  # default 2%
    if len(candles) >= 15:
        trs = []
        for i in range(min(14, len(candles) - 1)):
            h = highs[i]
            l = lows[i]
            pc = closes[i + 1]
            if h > 0 and l > 0 and pc > 0:
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if trs and today_close > 0:
            atr_pct = (sum(trs) / len(trs)) / today_close

    metrics = {
        "ma20": ma20, "ma50": ma50, "ma200": ma200, "rsi": rsi,
        "atr_pct": atr_pct,  # v4.0
        "close": today_close, "volume": today_vol, "avg_vol20": avg_vol20,
    }

    if ma200 > 0 and ma50 <= ma200:
        # v6.15: MA50>MA200 못 만족시 단기 추세 fallback
        # v6.16: fallback 더 완화 — close>MA20 (단기 회복 종목도 허용)
        if today_close <= ma20:
            return False, f"MA 정배열 X & 종가≤MA20", metrics
    elif today_close <= ma20:
        return False, f"종가≤MA20", metrics
    # v6.16: RSI 45~80 → 35~85 (더 약세 + 더 강한 모멘텀 허용)
    if not (35 <= rsi <= 85):
        return False, f"RSI {rsi:.0f} 범위밖 (35~85)", metrics
    # v6.16: 거래량 1.0x → 0.7x (평균보다 적어도 OK, dead-stock 만 차단)
    if avg_vol20 > 0 and today_vol < avg_vol20 * 0.7:
        return False, f"거래량 부족 (<{avg_vol20*0.7:.0f})", metrics

    # 20일 고점 돌파 OR MA20 위 (이미 위에서 MA20 체크했으니 항상 통과)
    breakout = today_close > high_20

    pattern = "20일고점돌파" if breakout else "MA20위"
    if ma200 > 0 and ma50 > ma200:
        trend_label = "MA50>200"
    elif ma50 > 0 and today_close > ma50:
        trend_label = "단기추세"
    else:
        trend_label = "약추세"
    reason = f"{pattern} {trend_label} RSI={rsi:.0f}"
    return True, reason, metrics

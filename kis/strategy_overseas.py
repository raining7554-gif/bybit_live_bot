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


# ═══════════════════════════════════════════════════════
# 일봉 조회 (해외)
# ═══════════════════════════════════════════════════════
def get_overseas_daily(ticker: str, exchange: str, count: int = 200) -> list:
    """해외 일봉 조회"""
    try:
        data = api.get(
            "/uapi/overseas-price/v1/quotations/dailyprice",
            "HHDFS76240000",
            {
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": ticker,
                "GUBN": "0",  # 0=일, 1=주, 2=월
                "BYMD": "",
                "MODP": "1",
            },
        )
        if data.get("rt_cd") != "0":
            return []
        outputs = data.get("output2", [])
        result = []
        for o in outputs[:count]:
            try:
                result.append({
                    "date":   o.get("xymd", ""),
                    "close":  float(o.get("clos", 0)),
                    "high":   float(o.get("high", 0)),
                    "low":    float(o.get("low", 0)),
                    "volume": int(float(o.get("tvol", 0))),
                })
            except (ValueError, TypeError):
                continue
        return result
    except Exception as e:
        print(f"[OS_STRATEGY] {ticker} 일봉 조회 오류: {e}")
        return []


def get_overseas_current(ticker: str, exchange: str) -> dict:
    try:
        data = api.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
        )
        if data.get("rt_cd") == "0":
            o = data.get("output", {})
            return {
                "price": float(o.get("last", 0)),
                "change_rate": float(o.get("rate", 0)),
                "volume": int(float(o.get("tvol", 0))),
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

    metrics = {
        "ma20": ma20, "ma50": ma50, "ma200": ma200, "rsi": rsi,
        "close": today_close, "volume": today_vol, "avg_vol20": avg_vol20,
    }

    if ma200 > 0 and ma50 <= ma200:
        return False, f"MA50({ma50:.1f})≤MA200({ma200:.1f})", metrics
    if today_close <= ma20:
        return False, f"종가≤MA20", metrics
    if not (50 <= rsi <= 70):
        return False, f"RSI {rsi:.0f} 범위밖", metrics
    if avg_vol20 > 0 and today_vol < avg_vol20 * 1.3:
        return False, f"거래량 부족", metrics

    # 20일 고점 돌파 OR 20일선 되돌림
    breakout = today_close > high_20
    pullback = today_close > ma20 and today_close < ma20 * 1.03  # MA20 0~3% 위
    if not (breakout or pullback):
        return False, "브레이크아웃/되돌림 패턴 아님", metrics

    pattern = "20일고점돌파" if breakout else "MA20되돌림"
    reason = f"{pattern} MA50>200 RSI={rsi:.0f}"
    return True, reason, metrics

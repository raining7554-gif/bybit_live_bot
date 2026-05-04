"""전략 v3.0 — 섹터 모멘텀 스윙

엔트리:
  - 일봉 기준 MA20 > MA60 (장기 정배열)
  - 종가 > MA20
  - 5일선 > 20일선 (단기 정배열)
  - 당일 거래량 >= 20일 평균 × 1.3
  - 일목 구름대 위 (전환선 > 기준선 단순화)
  - 섹터 스크리닝은 scanner 단계에서 이미 통과

청산 (SwingStop):
  - -3% 하드 손절
  - +3% 수익 후 고점 대비 -5% 트레일링
  - 20일선 이탈 (monitor EOD에서 체크)
  - 최대 10영업일 경과
"""
import kis_auth as api
from config import (
    DOM_STOP_LOSS, DOM_TRAIL_ACTIVATE, DOM_TRAIL_DROP,
    DOM_MAX_HOLD_DAYS,
)

KOSPI_CODE = "0001"


# ═══════════════════════════════════════════════════════
# 유틸: 일봉 데이터 조회
# ═══════════════════════════════════════════════════════
def get_daily_candles(ticker: str, market_code: str = "J", count: int = 60) -> list:
    """일봉 데이터 조회 (최근 count개). 리턴: [{close, high, low, volume, date}, ...] 최신순"""
    try:
        data = api.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "FHKST01010400",
            {
                "fid_cond_mrkt_div_code": market_code,
                "fid_input_iscd": ticker,
                "fid_org_adj_prc": "1",
                "fid_period_div_code": "D",
            },
        )
        outputs = data.get("output2") or data.get("output") or []
        result = []
        for o in outputs[:count]:
            try:
                result.append({
                    "date":   o.get("stck_bsop_date", ""),
                    "close":  float(o.get("stck_clpr", 0)),
                    "high":   float(o.get("stck_hgpr", 0)),
                    "low":    float(o.get("stck_lwpr", 0)),
                    "volume": int(float(o.get("acml_vol", 0))),
                })
            except (ValueError, TypeError):
                continue
        return result
    except Exception as e:
        print(f"[STRATEGY] {ticker} 일봉 조회 오류: {e}")
        return []


def _ma(values: list, period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[:period]) / period


def _rsi(closes: list, period: int = 14) -> float:
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
# 시장 국면
# ═══════════════════════════════════════════════════════
def get_market_regime() -> dict:
    """KOSPI 기반 국면 판단: BULL / SIDEWAYS / BEAR / CRASH"""
    try:
        candles = get_daily_candles(KOSPI_CODE, market_code="U", count=25)
        if len(candles) < 20:
            return {"regime": "BULL", "ma5": 0, "ma20": 0, "rsi": 50}

        closes = [c["close"] for c in candles]
        ma5  = _ma(closes, 5)
        ma20 = _ma(closes, 20)
        rsi  = _rsi(closes)

        if rsi < 30 and ma5 < ma20 * 0.97:
            regime = "CRASH"
        elif ma5 < ma20 * 0.995:
            regime = "BEAR"
        elif ma5 > ma20 * 1.005:
            regime = "BULL"
        else:
            regime = "SIDEWAYS"

        print(f"[REGIME] {regime} MA5={ma5:.0f} MA20={ma20:.0f} RSI={rsi:.1f}")
        return {"regime": regime, "ma5": ma5, "ma20": ma20, "rsi": rsi}
    except Exception as e:
        print(f"[REGIME] 오류: {e}")
    return {"regime": "BULL", "ma5": 0, "ma20": 0, "rsi": 50}


# ═══════════════════════════════════════════════════════
# 스윙 진입 조건
# ═══════════════════════════════════════════════════════
def check_swing_entry(ticker: str, name: str = "") -> tuple:
    """일봉 기반 스윙 진입 조건 체크

    Returns: (ok: bool, reason: str, metrics: dict)
    """
    candles = get_daily_candles(ticker, "J", count=60)
    if len(candles) < 25:
        return False, "일봉 데이터 부족", {}

    closes = [c["close"] for c in candles]
    highs  = [c["high"] for c in candles]
    lows   = [c["low"] for c in candles]
    vols   = [c["volume"] for c in candles]

    ma5   = _ma(closes, 5)
    ma20  = _ma(closes, 20)
    ma60  = _ma(closes, 60) if len(closes) >= 60 else _ma(closes, len(closes))
    today_close = closes[0]
    today_vol   = vols[0]
    avg_vol_20  = sum(vols[1:21]) / 20 if len(vols) >= 21 else sum(vols) / len(vols)

    # 일목 전환선(9일 고저 평균), 기준선(26일 고저 평균)
    def _ichimoku_line(highs_, lows_, period):
        if len(highs_) < period:
            return 0.0
        return (max(highs_[:period]) + min(lows_[:period])) / 2

    tenkan = _ichimoku_line(highs, lows, 9)
    kijun  = _ichimoku_line(highs, lows, 26) if len(highs) >= 26 else tenkan

    metrics = {
        "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "close": today_close, "volume": today_vol, "avg_vol20": avg_vol_20,
        "tenkan": tenkan, "kijun": kijun,
    }

    # 1) 장기 정배열
    if ma60 > 0 and ma20 <= ma60:
        return False, f"MA20({ma20:.0f})≤MA60({ma60:.0f}) 장기 하락", metrics

    # 2) 단기 정배열
    if ma5 <= ma20:
        return False, f"MA5({ma5:.0f})≤MA20({ma20:.0f}) 단기 약세", metrics

    # 3) 현재가가 MA20 위
    if today_close <= ma20:
        return False, f"종가({today_close:.0f})≤MA20({ma20:.0f})", metrics

    # 4) 거래량 증가
    if avg_vol_20 > 0 and today_vol < avg_vol_20 * 1.3:
        ratio = today_vol / avg_vol_20 if avg_vol_20 else 0
        return False, f"거래량 {ratio:.1f}배 (1.3배 미만)", metrics

    # 5) 일목 전환선 > 기준선 (구름대 단순화)
    if tenkan > 0 and kijun > 0 and tenkan <= kijun:
        return False, f"일목 전환선({tenkan:.0f})≤기준선({kijun:.0f})", metrics

    reason = (
        f"MA정배열(5>{ma5:.0f}/20>{ma20:.0f}/60>{ma60:.0f}) "
        f"거래량 {today_vol/avg_vol_20:.1f}배 일목양호"
    )
    return True, reason, metrics


# ═══════════════════════════════════════════════════════
# 스윙 스탑 (트레일링 + 하드 손절)
# ═══════════════════════════════════════════════════════
class SwingStop:
    def __init__(self, buy_price: float, entry_date: str = ""):
        self.buy_price = buy_price
        self.peak_price = buy_price
        self.activated = False
        self.entry_date = entry_date

    def update_intraday(self, current_price: float) -> tuple:
        """장중 분봉용 체크: 하드 손절 + 트레일링"""
        if current_price > self.peak_price:
            self.peak_price = current_price

        pnl = (current_price - self.buy_price) / self.buy_price

        # 하드 손절
        if pnl <= -DOM_STOP_LOSS:
            return True, f"손절 ({pnl*100:+.2f}%)"

        # 트레일링 활성화
        if not self.activated and pnl >= DOM_TRAIL_ACTIVATE:
            self.activated = True
            print(f"[TRAIL] 활성화 peak={self.peak_price:.0f} pnl={pnl*100:+.2f}%")

        if self.activated:
            drop = (current_price - self.peak_price) / self.peak_price
            if drop <= -DOM_TRAIL_DROP:
                return True, f"트레일링 청산 ({pnl*100:+.2f}% / 고점대비 {drop*100:.1f}%)"

        return False, ""


# ═══════════════════════════════════════════════════════
# 일봉 청산 조건 (EOD 체크용)
# ═══════════════════════════════════════════════════════
def check_eod_exit(ticker: str, buy_price: float, hold_days: int) -> tuple:
    """장 마감 직전 일봉 기준 청산 조건 체크

    Returns: (should_exit: bool, reason: str)
    """
    # 최대 보유일 경과
    if hold_days >= DOM_MAX_HOLD_DAYS:
        return True, f"최대 보유 {DOM_MAX_HOLD_DAYS}영업일 경과"

    candles = get_daily_candles(ticker, "J", count=25)
    if len(candles) < 20:
        return False, "데이터 부족"

    closes = [c["close"] for c in candles]
    today_close = closes[0]
    ma20 = _ma(closes, 20)
    ma5  = _ma(closes, 5)

    # 20일선 이탈 (종가 기준)
    if today_close < ma20 * 0.98:  # 2% 버퍼
        return True, f"MA20 이탈 ({today_close:.0f} < {ma20:.0f})"

    # 5일 < 20일 (단기 데드크로스)
    if ma5 < ma20 * 0.99:
        return True, f"5일선 데드크로스"

    return False, ""


# ═══════════════════════════════════════════════════════
# 레거시 호환
# ═══════════════════════════════════════════════════════
TrailingStop = SwingStop  # 기존 코드 호환


def get_position_size_pct(ticker: str) -> float:
    """레거시 호환 — 이제는 config의 DOM_POSITION_PCT 사용"""
    from config import DOM_POSITION_PCT
    return DOM_POSITION_PCT


def is_valid_entry(*args, **kwargs):
    """레거시 호환. 실제 판단은 check_swing_entry로."""
    return False, "사용안함", ""

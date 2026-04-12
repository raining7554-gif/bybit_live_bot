"""
바이비트 선물 실전 봇 v5.5
══════════════════════════════════════════════════
심볼: BTCUSDT / ETHUSDT / XRPUSDT / LINKUSDT / SOLUSDT
레버리지: 15배

v5.0 → v5.1 변경사항
──────────────────────────
[심볼]
- SOLUSDT 추가 (5개 심볼)

[파라미터 최적화 - 백테스트 기반]
- ST_SIZE_PCT   : 0.30 → 0.28  (추세 비중 소폭 축소)
- ST_SL_PCT     : 0.007 → 0.008 (추세 손절 -0.8%로 소폭 완화)
- SW_SIZE_PCT   : 0.15 → 0.18  (횡보 비중 확대)
- SW_SL_PCT     : 0.004 → 0.005 (횡보 손절 -0.5%로 소폭 완화)
- SW_TP_PCT     : 0.008 → 0.010 (횡보 익절 +1.0%로 확대)

[전략 구조 유지]
- STRONG_TREND : 강한 추세 (ADX>28 + BB>2.5% + DI갭>10)
- SIDEWAYS     : 횡보 (ADX<20 + BB<2.2% + BB경계 역추세)
- WATCH        : 관망 (약한추세/고변동/전환구간)
- 멀티타임프레임 (15분봉 + 1시간봉)
- 3연속 손절 → 8시간 쿨다운
- 월별 손실 한도 -15%
"""

from pybit.unified_trading import HTTP
import time
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import os, sys, traceback
import requests
import pytz

KST = pytz.timezone("Asia/Seoul")
def now_kst(): return datetime.now(KST)

# ══════════════════════════════════════════════════
# ⚙️  환경변수 설정 (에이전트가 Railway API로 변경)
# ══════════════════════════════════════════════════
API_KEY       = os.environ.get("BYBIT_API_KEY", "")
API_SECRET    = os.environ.get("BYBIT_API_SECRET", "")
TG_TOKEN      = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID    = os.environ.get("TG_CHAT_ID", "")
TESTNET       = os.environ.get("TESTNET", "false").lower() == "true"
POSITION_MODE = os.environ.get("POSITION_MODE", "one_way")  # "one_way" or "hedge"

# ── 심볼 & 기본 설정 ──────────────────────────────
SYMBOLS       = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]  # v5.5: 5개 심볼
LEVERAGE      = int(os.environ.get("LEVERAGE", "10"))  # v5.5: 10배로 변경
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "4"))  # v5.5: 4개로 확대
MAX_SAME_DIR  = int(os.environ.get("MAX_SAME_DIR", "3"))  # v5.5: 3개로 확대
LOOP_SEC      = 20  # v5.5: 20초 루프 (Rate Limit 방지)
MIN_HOLD_SEC  = 180

# ── 시장 판단 기준 (환경변수로 에이전트가 조정 가능) ──
ADX_STRONG    = float(os.environ.get("ADX_STRONG",    "28"))    # 강한추세 기준
ADX_SIDEWAYS  = float(os.environ.get("ADX_SIDEWAYS",  "20"))    # 횡보 기준
BB_STRONG     = float(os.environ.get("BB_STRONG",     "0.015")) # 강한추세 BB폭 (v5.5: 1.5%로 완화)
BB_SIDEWAYS   = float(os.environ.get("BB_SIDEWAYS",   "0.022")) # 횡보 BB폭
DI_GAP        = float(os.environ.get("DI_GAP",        "10"))    # DI+/- 최소 갭
ATR_VOL_MULT  = float(os.environ.get("ATR_VOL_MULT",  "1.8"))   # 고변동성 배수

# ── 강한 추세 전략 파라미터 (v5.1 최적화) ──────────
ST_SIZE_PCT   = float(os.environ.get("ST_SIZE_PCT",   "0.32"))  # 비중 32% (v5.5 확대)
ST_SL_PCT     = float(os.environ.get("ST_SL_PCT",     "0.008")) # 손절 -0.8% (↑0.7%)
ST_TRAIL_ACT  = float(os.environ.get("ST_TRAIL_ACT",  "0.012")) # 트레일 활성 +1.2%
ST_TRAIL_CB   = float(os.environ.get("ST_TRAIL_CB",   "0.004")) # 트레일 콜백 0.4%

# ── 횡보 전략 파라미터 (v5.1 최적화) ──────────────
SW_SIZE_PCT   = float(os.environ.get("SW_SIZE_PCT",   "0.22"))  # 비중 22% (v5.5 확대)
SW_SL_PCT     = float(os.environ.get("SW_SL_PCT",     "0.005")) # 손절 -0.5% (↑0.4%)
SW_TRAIL_ACT  = float(os.environ.get("SW_TRAIL_ACT",  "0.008")) # 트레일 활성 +0.8%
SW_TRAIL_CB   = float(os.environ.get("SW_TRAIL_CB",   "0.003")) # 트레일 콜백 0.3%
SW_TP_PCT     = float(os.environ.get("SW_TP_PCT",     "0.010")) # 고정익절 +1.0% (↑0.8%)

# ── 리스크 관리 ───────────────────────────────────
MONTHLY_MAX_LOSS = float(os.environ.get("MONTHLY_MAX_LOSS", "0.15")) # 월 -15% 한도
CONSEC_LOSS_MAX  = int(os.environ.get("CONSEC_LOSS_MAX", "3"))        # 연속손절 한도
COOLDOWN_CANDLES = int(os.environ.get("COOLDOWN_CANDLES", "32"))      # 쿨다운 32캔들=8시간
STABILITY_N      = int(os.environ.get("STABILITY_N", "3"))            # 안정성 필터 3캔들
FLASH_CRASH      = float(os.environ.get("FLASH_CRASH", "0.025"))      # 급락 즉시청산

# ── v5.5 추가: 약한추세 전략 ──
WEAK_ENABLED  = os.environ.get("WEAK_ENABLED", "true").lower() == "true"
WEAK_SIZE_PCT = float(os.environ.get("WEAK_SIZE_PCT", "0.15"))   # 비중 15%
WEAK_TP_PCT   = float(os.environ.get("WEAK_TP_PCT",   "0.008"))  # 익절 +0.8%
WEAK_SL_PCT   = float(os.environ.get("WEAK_SL_PCT",   "0.005"))  # 손절 -0.5%
WEAK_TRAIL_ACT= float(os.environ.get("WEAK_TRAIL_ACT","0.005"))  # 트레일 활성 +0.5%
WEAK_TRAIL_CB = float(os.environ.get("WEAK_TRAIL_CB", "0.002"))  # 트레일 콜백 0.2%
ADX_WEAK_MIN  = float(os.environ.get("ADX_WEAK_MIN",  "20"))     # 약한추세 ADX 최소
ADX_WEAK_MAX  = float(os.environ.get("ADX_WEAK_MAX",  "32"))     # 약한추세 ADX 최대

# ── v5.5 추가: 피라미딩 ──
PYR_ENABLED  = os.environ.get("PYR_ENABLED", "true").lower() == "true"
PYR_TRIGGER  = float(os.environ.get("PYR_TRIGGER", "0.020"))  # +2% 수익 시 추가진입
PYR_SIZE_PCT = float(os.environ.get("PYR_SIZE_PCT", "0.10"))   # 추가비중 10%
PYR_MAX      = int(os.environ.get("PYR_MAX", "2"))             # 최대 2회

# ── v5.5 추가: 동적비중 ──
DYN_SIZE_ENABLED = os.environ.get("DYN_SIZE_ENABLED", "true").lower() == "true"

# ── v5.5 추가: 단계별 트레일 ──
# TRAIL_LEVELS: 실제 가격% 기준 (레버리지 반영)
# 레버리지 10배 기준: 레버수익% / 10 = 실제가격%
# v5.5b: 타이트하게 조임 → 수익 더 빨리 보호
TRAIL_LEVELS = [
    (0.003, 0.002),   # 실제+0.3%(레버3%)  → 콜백 0.2%(레버2%)
    (0.007, 0.003),   # 실제+0.7%(레버7%)  → 콜백 0.3%(레버3%)
    (0.015, 0.005),   # 실제+1.5%(레버15%) → 콜백 0.5%(레버5%)
    (0.025, 0.008),   # 실제+2.5%(레버25%) → 콜백 0.8%(레버8%)
    (0.050, 0.015),   # 실제+5.0%(레버50%) → 콜백 1.5%(레버15%)
]

# ══════════════════════════════════════════════════
# 상태 관리
# ══════════════════════════════════════════════════
session = None
positions     = {}      # {symbol: {side, entry, size, mode, ...}}
mode_history  = {}      # {symbol: [mode1, mode2, ...]} 심볼별 모드 히스토리
prev_mode     = {}      # {symbol: str} 이전 모드 (변경 알림용)
cooldown      = {"strong_trend": 0, "sideways": 0}
consec_loss   = {"strong_trend": 0, "sideways": 0}
monthly_start = 0.0     # 월초 잔고
monthly_stop  = False   # 월 손실 한도 도달 시 True
entry_times   = {}      # {symbol: float}  진입 시각 (time.time())

# 1시간봉 캐시
h1_cache      = {}      # {symbol: (mode, timestamp)}
H1_CACHE_SEC  = 900     # 15분마다 갱신

# 전략별 성과 통계
trade_stats = {
    "strong_trend": {"wins": 0, "losses": 0, "total_pnl": 0.0},
    "sideways":     {"wins": 0, "losses": 0, "total_pnl": 0.0},
    "weak_trend":   {"wins": 0, "losses": 0, "total_pnl": 0.0},
}

# ── 전략 ON/OFF 토글 (텔레그램 버튼으로 제어) ──
strategy_enabled = {
    "strong_trend": True,
    "sideways":     True,
    "weak_trend":   True,
}

# 텔레그램 폴링 상태
tg_last_update_id = 0

# ══════════════════════════════════════════════════
# 텔레그램
# ══════════════════════════════════════════════════
def tg(msg: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        print(f"[TG] {msg}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        print(f"[TG Error] {e}")

def tg_send_strategy_menu(chat_id=None):
    """전략 ON/OFF 인라인 버튼 메시지 발송"""
    if not TG_TOKEN:
        return
    cid = chat_id or TG_CHAT_ID
    if not cid:
        return
    mode_kr = {"strong_trend": "강한추세", "sideways": "횡보", "weak_trend": "약한추세"}
    lines = ["📋 <b>전략 ON/OFF 설정</b>"]
    for m, kr in mode_kr.items():
        state = "✅ ON" if strategy_enabled[m] else "❌ OFF"
        lines.append(f"{kr}: {state}")
    text = "\n".join(lines)
    buttons = []
    for m, kr in mode_kr.items():
        label = f"{'✅' if strategy_enabled[m] else '❌'} {kr} 토글"
        buttons.append([{"text": label, "callback_data": f"toggle_{m}"}])
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": buttons},
            },
            timeout=5
        )
    except Exception as e:
        print(f"[TG Menu Error] {e}")

def tg_edit_strategy_menu(chat_id, message_id):
    """기존 메시지를 현재 전략 상태로 업데이트"""
    if not TG_TOKEN:
        return
    mode_kr = {"strong_trend": "강한추세", "sideways": "횡보", "weak_trend": "약한추세"}
    lines = ["📋 <b>전략 ON/OFF 설정</b>"]
    for m, kr in mode_kr.items():
        state = "✅ ON" if strategy_enabled[m] else "❌ OFF"
        lines.append(f"{kr}: {state}")
    text = "\n".join(lines)
    buttons = []
    for m, kr in mode_kr.items():
        label = f"{'✅' if strategy_enabled[m] else '❌'} {kr} 토글"
        buttons.append([{"text": label, "callback_data": f"toggle_{m}"}])
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": buttons},
            },
            timeout=5
        )
    except Exception as e:
        print(f"[TG Edit Error] {e}")

def tg_answer_callback(callback_query_id: str, text: str = ""):
    """콜백 쿼리 응답 (버튼 로딩 스피너 해제)"""
    if not TG_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=5
        )
    except Exception as e:
        print(f"[TG Callback Error] {e}")

def poll_telegram_updates():
    """텔레그램 업데이트 폴링 및 처리"""
    global tg_last_update_id
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
            params={"offset": tg_last_update_id + 1, "timeout": 0, "limit": 10},
            timeout=6
        )
        if r.status_code != 200:
            return
        updates = r.json().get("result", [])
        for upd in updates:
            tg_last_update_id = upd["update_id"]

            # /strategy 텍스트 명령어
            msg = upd.get("message", {})
            if msg:
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if text.strip() == "/strategy":
                    tg_send_strategy_menu(chat_id)
                continue

            # 인라인 버튼 콜백
            cbq = upd.get("callback_query", {})
            if cbq:
                data        = cbq.get("data", "")
                cbq_id      = cbq.get("id", "")
                chat_id     = str(cbq.get("message", {}).get("chat", {}).get("id", ""))
                message_id  = cbq.get("message", {}).get("message_id")

                if data.startswith("toggle_"):
                    mode_key = data[len("toggle_"):]
                    if mode_key in strategy_enabled:
                        strategy_enabled[mode_key] = not strategy_enabled[mode_key]
                        state_str = "ON" if strategy_enabled[mode_key] else "OFF"
                        mode_kr = {"strong_trend": "강한추세", "sideways": "횡보", "weak_trend": "약한추세"}
                        tg_answer_callback(cbq_id, f"{mode_kr.get(mode_key, mode_key)} → {state_str}")
                        tg_edit_strategy_menu(chat_id, message_id)
    except Exception as e:
        print(f"[TG Poll Error] {e}")

# ══════════════════════════════════════════════════
# 바이비트 API
# ══════════════════════════════════════════════════
def init_session():
    global session
    session = HTTP(
        testnet=TESTNET,
        api_key=API_KEY,
        api_secret=API_SECRET
    )
    for sym in SYMBOLS:
        try:
            session.set_leverage(
                category="linear",
                symbol=sym,
                buyLeverage=str(LEVERAGE),
                sellLeverage=str(LEVERAGE)
            )
        except Exception:
            pass

def get_balance() -> float:
    try:
        r = session.get_wallet_balance(accountType="UNIFIED")
        return float(r["result"]["list"][0]["totalEquity"])
    except Exception as e:
        print(f"[잔고 오류] {e}")
        return 0.0

def get_price(symbol: str) -> float:
    try:
        r = session.get_tickers(category="linear", symbol=symbol)
        return float(r["result"]["list"][0]["lastPrice"])
    except Exception:
        return 0.0

def get_ohlcv(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    """interval: '15' (15분봉), '60' (1시간봉)"""
    try:
        r = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit
        )
        rows = r["result"]["list"]
        df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","turnover"])
        df = df.astype({"open":float,"high":float,"low":float,"close":float,"volume":float})
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception as e:
        print(f"[OHLCV 오류 {symbol}] {e}")
        return pd.DataFrame()

def get_open_positions() -> dict:
    try:
        r = session.get_positions(category="linear", settleCoin="USDT")
        result = {}
        for p in r["result"]["list"]:
            if float(p["size"]) > 0:
                result[p["symbol"]] = {
                    "side":  p["side"],
                    "size":  float(p["size"]),
                    "entry": float(p["avgPrice"]),
                    "pnl":   float(p["unrealisedPnl"])
                }
        return result
    except Exception as e:
        print(f"[포지션 오류] {e}")
        return {}

def _get_position_idx(side: str) -> int:
    """POSITION_MODE에 따라 positionIdx 반환"""
    if POSITION_MODE == "hedge":
        return 1 if side == "Buy" else 2
    return 0  # one_way

def place_order(symbol: str, side: str, qty: float) -> bool:
    try:
        r = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            positionIdx=_get_position_idx(side),
        )
        return r["retCode"] == 0
    except Exception as e:
        print(f"[주문 오류 {symbol}] {e}")
        return False

def close_position(symbol: str, pos: dict) -> bool:
    close_side = "Sell" if pos["side"] == "Buy" else "Buy"
    return place_order(symbol, close_side, pos["size"])

# ══════════════════════════════════════════════════
# 지표 계산
# ══════════════════════════════════════════════════
def calc_indicators(df: pd.DataFrame) -> dict:
    if len(df) < 60:
        return {}
    c = df["close"]
    h = df["high"]
    l = df["low"]

    ema20 = c.ewm(span=20).mean().iloc[-1]
    ema50 = c.ewm(span=50).mean().iloc[-1]

    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_up  = (bb_mid + 2*bb_std).iloc[-1]
    bb_low = (bb_mid - 2*bb_std).iloc[-1]
    bb_mid_v = bb_mid.iloc[-1]
    bb_width = (bb_up - bb_low) / bb_mid_v if bb_mid_v > 0 else 0
    bb_pos   = (c.iloc[-1] - bb_low) / (bb_up - bb_low) if (bb_up - bb_low) > 0 else 0.5

    delta = c.diff()
    g = delta.clip(lower=0).rolling(14).mean()
    lo = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = (100 - (100 / (1 + g / lo.replace(0, 1e-9)))).iloc[-1]

    # ── ADX 정확한 계산 (v5.5 버그 수정) ──
    tr   = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    dmp  = (h - h.shift()).clip(lower=0)
    dmm  = (l.shift() - l).clip(lower=0)
    atr14   = tr.rolling(14).mean()
    dip_ser = 100 * dmp.rolling(14).mean() / atr14.replace(0, 1e-9)
    dim_ser = 100 * dmm.rolling(14).mean() / atr14.replace(0, 1e-9)
    dx_ser  = 100 * (dip_ser - dim_ser).abs() / (dip_ser + dim_ser).replace(0, 1e-9)
    adx_ser = dx_ser.rolling(14).mean()
    adx = adx_ser.iloc[-1]
    dip = dip_ser.iloc[-1]
    dim = dim_ser.iloc[-1]

    atr     = atr14.iloc[-1]
    atr_pct = atr / c.iloc[-1] if c.iloc[-1] > 0 else 0
    atr_ma  = atr14.rolling(20).mean().iloc[-1]

    vol_ma    = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = df["volume"].iloc[-1] / vol_ma if vol_ma > 0 else 1

    upper_wick = (h - df[["open","close"]].max(axis=1)).iloc[-1]
    lower_wick = (df[["open","close"]].min(axis=1) - l).iloc[-1]
    body       = abs(df["close"] - df["open"]).iloc[-1]

    rsi_h5 = c.rolling(5).apply(lambda x: pd.Series(x).ewm(span=3).mean().iloc[-1]).rolling(5).max().iloc[-1]
    rsi_l5 = c.rolling(5).apply(lambda x: pd.Series(x).ewm(span=3).mean().iloc[-1]).rolling(5).min().iloc[-1]
    # 더 단순하게
    rsi_series = 100 - (100 / (1 + g / lo.replace(0, 1e-9)))
    rsi_h5 = rsi_series.rolling(5).max().iloc[-1]
    rsi_l5 = rsi_series.rolling(5).min().iloc[-1]

    return {
        "price":      c.iloc[-1],
        "ema20":      ema20,
        "ema50":      ema50,
        "bb_mid":     bb_mid_v,
        "bb_width":   bb_width,
        "bb_pos":     bb_pos,
        "rsi":        rsi,
        "adx":        adx,
        "di_plus":    dip,
        "di_minus":   dim,
        "atr":        atr,
        "atr_pct":    atr_pct,
        "atr_ma":     atr_ma,
        "vol_ratio":  vol_ratio,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "body":       body,
        "rsi_h5":     rsi_h5,
        "rsi_l5":     rsi_l5,
    }

# ══════════════════════════════════════════════════
# 시장 모드 판단
# ══════════════════════════════════════════════════
def detect_mode(ind: dict) -> str:  # v5.5: weak_trend 추가
    """
    strong_trend : 강한 추세 → 추세 추종 전략
    sideways     : 횡보      → BB 역추세 전략
    high_vol     : 고변동성  → 관망
    unclear      : 애매      → 관망
    """
    if not ind:
        return "unclear"

    adx       = ind["adx"]
    bb_width  = ind["bb_width"]
    di_plus   = ind["di_plus"]
    di_minus  = ind["di_minus"]
    atr_pct   = ind["atr_pct"]
    atr_ma    = ind["atr_ma"]
    di_gap    = abs(di_plus - di_minus)
    atr_ratio = atr_pct / atr_ma if atr_ma > 0 else 1

    # 고변동성 먼저 체크
    if atr_ratio > ATR_VOL_MULT or bb_width > 0.05:
        return "high_vol"

    # 강한 추세
    if adx > ADX_STRONG and bb_width > BB_STRONG and di_gap > DI_GAP:
        return "strong_trend"

    # 횡보: ADX 낮고 BB 좁지만 최소 1.5% 이상이어야 진입 의미있음
    if adx < ADX_SIDEWAYS and 0.015 < bb_width < BB_SIDEWAYS:
        return "sideways"

    # 약한추세 (v5.5): ADX 20~32, 방향성 있지만 강하지 않은 구간
    di_gap = abs(ind.get("di_plus", 0) - ind.get("di_minus", 0))
    if ADX_WEAK_MIN <= adx <= ADX_WEAK_MAX and di_gap > 6 and WEAK_ENABLED:
        return "weak_trend"

    return "unclear"

def get_h1_mode(symbol: str) -> str:
    """1시간봉 모드 캐시 (15분마다 갱신)"""
    now = time.time()
    if symbol in h1_cache:
        cached_mode, cached_time = h1_cache[symbol]
        if now - cached_time < H1_CACHE_SEC:
            return cached_mode

    df1h = get_ohlcv(symbol, "60", 80)
    ind1h = calc_indicators(df1h)
    mode = detect_mode(ind1h)
    h1_cache[symbol] = (mode, now)
    return mode

def get_final_mode(m15: str, m1h: str) -> str:
    """
    멀티 타임프레임 최종 모드 결정
    - 둘 다 같으면 → 그 모드
    - 1H strong_trend + 15M weak_trend → strong_trend (상위 추세 우선)
    - 1H sideways     + 15M weak_trend → sideways     (상위 횡보 우선)
    - 1H unclear      → 15분봉 신뢰
    - 1H high_vol     → watch
    - 나머지 충돌     → watch
    """
    if m15 in ("unclear", "high_vol"):
        return "watch"
    if m1h == m15:
        return m15
    if m1h == "unclear":
        return m15
    if m1h == "high_vol":
        return "watch"
    # 1H 상위 타임프레임이 명확한 모드일 때 weak_trend 충돌 해소
    if m1h == "strong_trend" and m15 == "weak_trend":
        return "strong_trend"
    if m1h == "sideways" and m15 == "weak_trend":
        return "sideways"
    return "watch"      # 나머지 충돌 → 관망

def is_stable_mode(symbol: str, mode: str) -> bool:
    """심볼의 최근 STABILITY_N회 동안 같은 모드인지 확인"""
    hist = mode_history.get(symbol, [])
    if len(hist) < STABILITY_N:
        return False
    return all(m == mode for m in hist[-STABILITY_N:])

# ══════════════════════════════════════════════════
# 진입 신호
# ══════════════════════════════════════════════════
def get_strong_trend_signal(ind: dict) -> str:
    """강한 추세 진입 신호: LONG / SHORT / NONE"""
    ema_long  = ind["ema20"] > ind["ema50"]
    ema_short = ind["ema20"] < ind["ema50"]
    di_long   = ind["di_plus"]  > ind["di_minus"] + DI_GAP
    di_short  = ind["di_minus"] > ind["di_plus"]  + DI_GAP

    long_ok  = ema_long  and di_long  and ind["rsi"] < 68
    short_ok = ema_short and di_short and ind["rsi"] > 32

    if long_ok:  return "LONG"
    if short_ok: return "SHORT"
    return "NONE"

def get_sideways_signal(ind: dict) -> str:
    """횡보 진입 신호: SHORT (상단) / LONG (하단) / NONE"""
    vw  = ind["vol_ratio"] < 0.85
    uw  = ind["upper_wick"] > ind["body"] * 0.5
    lw  = ind["lower_wick"] > ind["body"] * 0.5
    rdt = ind["rsi"] < ind["rsi_h5"] * 0.97
    rdb = ind["rsi"] > ind["rsi_l5"] * 1.03

    # BB 상단 → 숏 (3개 조건 중 2개)
    if ind["bb_pos"] > 0.88 and ind["rsi"] > 60:
        if sum([vw, uw, rdt]) >= 2:
            return "SHORT"

    # BB 하단 → 롱 (3개 조건 중 2개)
    if ind["bb_pos"] < 0.12 and ind["rsi"] < 40:
        if sum([vw, lw, rdb]) >= 2:
            return "LONG"

    return "NONE"

# ══════════════════════════════════════════════════
# 수량 계산
# ══════════════════════════════════════════════════
def calc_qty(balance: float, size_pct: float, price: float, symbol: str) -> float:
    """증거금 기준 수량 계산"""
    margin = balance * size_pct
    notional = margin * LEVERAGE
    qty = notional / price

    # 심볼별 최소 수량 / 소수점 처리
    decimals = {
        "BTCUSDT":  3,
        "ETHUSDT":  2,
        "XRPUSDT":  0,
        "LINKUSDT": 1,
        "SOLUSDT":  1,   # v5.5 수정: 바이비트 SOL 소수점 1자리
    }
    d = decimals.get(symbol, 2)
    qty = round(qty, d)

    # 최소 주문 금액 $5 이상
    if qty * price < 5:
        return 0.0

    return qty

# ══════════════════════════════════════════════════
# 포지션 청산 로직
# ══════════════════════════════════════════════════
def check_exit(symbol: str, pos: dict, price: float, ind: dict) -> str:
    """
    청산 조건 체크
    반환: 'sl' | 'trail' | 'tp' | 'flash' | ''
    """
    entry = pos["entry"]
    side  = pos["side"]

    if side == "Buy":
        pnl_pct = (price - entry) / entry
    else:
        pnl_pct = (entry - price) / entry

    # 피크 업데이트
    if pnl_pct > pos.get("peak", 0):
        pos["peak"] = pnl_pct

    mode = pos.get("mode", "strong_trend")

    # ── 급락 즉시 청산 ──
    if pnl_pct <= -FLASH_CRASH:
        return "flash"

    # ── 강한 추세 청산 (v5.5: 단계별 트레일) ──
    if mode == "strong_trend":
        if pnl_pct <= -ST_SL_PCT:
            return "sl"
        peak = pos.get("peak", 0)
        if peak >= TRAIL_LEVELS[0][0]:
            cb = TRAIL_LEVELS[-1][1]
            for threshold, callback in TRAIL_LEVELS:
                if peak >= threshold:
                    cb = callback
            if pnl_pct < peak - cb:
                return "trail"

    # ── 횡보 청산 ──
    elif mode == "sideways":
        # 고정 익절
        if pnl_pct >= SW_TP_PCT:
            return "tp"
        # 손절
        if pnl_pct <= -SW_SL_PCT:
            return "sl"
        # 트레일
        if pos.get("peak", 0) >= SW_TRAIL_ACT and pnl_pct < pos["peak"] - SW_TRAIL_CB:
            return "trail"

    # ── 약한추세 청산 (v5.5) ──
    elif mode == "weak_trend":
        if pnl_pct >= WEAK_TP_PCT:
            return "tp"
        if pnl_pct <= -WEAK_SL_PCT:
            return "sl"
        if pos.get("peak", 0) >= WEAK_TRAIL_ACT and pnl_pct < pos["peak"] - WEAK_TRAIL_CB:
            return "trail"

    return ""

# ══════════════════════════════════════════════════
# 쿨다운 & 월별 한도 관리
# ══════════════════════════════════════════════════
def update_cooldown():
    for k in cooldown:
        if cooldown[k] > 0:
            cooldown[k] -= 1

def on_loss(mode: str):
    """손절 발생 시 호출"""
    consec_loss[mode] = consec_loss.get(mode, 0) + 1
    if consec_loss[mode] >= CONSEC_LOSS_MAX:
        cooldown[mode] = COOLDOWN_CANDLES
        consec_loss[mode] = 0
        tg(f"⚠️ [{mode}] 3연속 손절 → 8시간 쿨다운 시작")

def on_win(mode: str):
    consec_loss[mode] = 0

def check_monthly_limit(balance: float) -> bool:
    """월별 손실 한도 체크"""
    global monthly_stop
    if monthly_start <= 0:
        return False
    loss_pct = (balance - monthly_start) / monthly_start
    if loss_pct <= -MONTHLY_MAX_LOSS:
        monthly_stop = True
        tg(f"🚨 월별 손실 한도 도달 ({loss_pct*100:.1f}%) → 봇 정지")
        return True
    return False

# ══════════════════════════════════════════════════
# 메인 루프
# ══════════════════════════════════════════════════
def run_loop():
    global monthly_start, monthly_stop, mode_history, prev_mode

    loop_count = 0
    last_report = time.time()
    REPORT_SEC = 3600  # 1시간마다 리포트

    tg(f"""🚀 바이비트 봇 v5.5 시작
심볼: {', '.join(SYMBOLS)}
레버리지: {LEVERAGE}배
포지션모드: {POSITION_MODE}
전략: 3모드 (강한추세/횡보/관망)
추세: 비중{ST_SIZE_PCT*100:.0f}% 손절{ST_SL_PCT*100:.1f}% 트레일5단계
횡보: 비중{SW_SIZE_PCT*100:.0f}% 익절{SW_TP_PCT*100:.1f}%
약한추세: {"ON" if WEAK_ENABLED else "OFF"} (비중{WEAK_SIZE_PCT*100:.0f}% 익절{WEAK_TP_PCT*100:.1f}%)
피라미딩: {"ON" if PYR_ENABLED else "OFF"} (+{PYR_TRIGGER*100:.0f}%시 {PYR_SIZE_PCT*100:.0f}% 추가)
동적비중: {"ON" if DYN_SIZE_ENABLED else "OFF"}
테스트넷: {TESTNET}""")

    while True:
        try:
            loop_count += 1
            update_cooldown()

            # ── 텔레그램 업데이트 폴링 ──
            poll_telegram_updates()

            balance = get_balance()
            if balance <= 0:
                time.sleep(LOOP_SEC)
                continue

            # 월초 잔고 초기화
            if monthly_start <= 0:
                monthly_start = balance
                tg(f"📅 월초 잔고 설정: ${monthly_start:,.2f}")

            # 월별 손실 한도 체크
            if check_monthly_limit(balance):
                time.sleep(3600)
                continue

            # 현재 포지션 조회
            open_pos = get_open_positions()
            long_cnt  = sum(1 for p in open_pos.values() if p["side"] == "Buy")
            short_cnt = sum(1 for p in open_pos.values() if p["side"] == "Sell")

            # ── 포지션 청산 체크 ──
            for sym, api_pos in open_pos.items():
                price = get_price(sym)
                if price <= 0:
                    continue

                local_pos = positions.get(sym, {})
                if not local_pos:
                    # v5.5 버그수정: 재시작시 peak를 현재 pnl로 초기화
                    # 기존: peak=0 → 트레일 활성화 지연
                    # 수정: 현재 수익률로 peak 초기화 → 즉시 트레일 가능
                    entry_p = api_pos["entry"]
                    if api_pos["side"] == "Buy":
                        cur_pnl = (price - entry_p) / entry_p
                    else:
                        cur_pnl = (entry_p - price) / entry_p
                    init_peak = max(0.0, cur_pnl)
                    local_pos = {
                        "mode":  "strong_trend",
                        "peak":  init_peak,
                        "entry": entry_p,
                        "side":  api_pos["side"]
                    }
                    positions[sym] = local_pos
                    if init_peak >= ST_TRAIL_ACT:
                        tg(f"🔄 {sym} 포지션 복구 | peak={init_peak*100:.2f}% → 트레일 즉시 활성")

                local_pos["entry"] = api_pos["entry"]
                local_pos["side"]  = api_pos["side"]

                # reason 먼저 체크 후 피라미딩 판단
                reason = check_exit(sym, local_pos, price, {})

                # ── MIN_HOLD_SEC 체크: flash 제외, 나머지는 보유시간 미달 시 청산 스킵 ──
                if reason and reason != "flash":
                    entry_ts = entry_times.get(sym, 0)
                    if entry_ts > 0 and (time.time() - entry_ts) < MIN_HOLD_SEC:
                        reason = ""  # 최소 보유시간 미경과 → 청산 보류

                # ── v5.5 피라미딩 ──
                if PYR_ENABLED and not reason:
                    pyr_count = local_pos.get("pyr_count", 0)
                    if pyr_count < PYR_MAX:
                        entry = local_pos.get("entry", price)
                        side  = local_pos.get("side", "Buy")
                        if side == "Buy":
                            cur_pnl = (price - entry) / entry
                        else:
                            cur_pnl = (entry - price) / entry
                        last_pyr = local_pos.get("last_pyr_price", entry)
                        if (cur_pnl >= PYR_TRIGGER and
                                abs(price - last_pyr) / last_pyr > 0.005):
                            qty2 = calc_qty(balance, PYR_SIZE_PCT, price, sym)
                            if qty2 > 0:
                                try:
                                    pyr_side = "Buy" if side == "Buy" else "Sell"
                                    session.place_order(
                                        category="linear", symbol=sym,
                                        side=pyr_side,
                                        orderType="Market", qty=str(qty2),
                                        positionIdx=_get_position_idx(pyr_side),
                                    )
                                    local_pos["pyr_count"] = pyr_count + 1
                                    local_pos["last_pyr_price"] = price
                                    tg(f"📈 {sym} 피라미딩 #{pyr_count+1}\n"
                                       f"수익: {cur_pnl*100:+.2f}% → 추가 {PYR_SIZE_PCT*100:.0f}%")
                                except Exception as e:
                                    print(f"[피라미딩 오류] {e}")

                if reason:
                    pnl = api_pos["pnl"]
                    ok  = close_position(sym, api_pos)
                    if ok:
                        mode = local_pos.get("mode", "strong_trend")
                        pnl_pct = (price - api_pos["entry"]) / api_pos["entry"]
                        if api_pos["side"] == "Sell":
                            pnl_pct = -pnl_pct

                        emoji = "✅" if pnl >= 0 else "❌"
                        reason_kr = {"sl":"손절","trail":"트레일청산","tp":"익절","flash":"급락청산"}.get(reason, reason)

                        tg(f"""{emoji} {sym} {reason_kr}
모드: {mode}
손익: ${pnl:+.2f} ({pnl_pct*100:+.2f}%)
잔고: ${balance:,.2f}""")

                        if pnl < 0:
                            on_loss(mode)
                        else:
                            on_win(mode)

                        # 전략별 통계 누적
                        if mode in trade_stats:
                            trade_stats[mode]["total_pnl"] += pnl
                            if pnl >= 0:
                                trade_stats[mode]["wins"] += 1
                            else:
                                trade_stats[mode]["losses"] += 1

                        positions.pop(sym, None)
                        entry_times.pop(sym, None)

            # ── 진입 판단 ──
            open_pos = get_open_positions()
            pos_count = len(open_pos)

            if pos_count >= MAX_POSITIONS:
                time.sleep(LOOP_SEC)
                continue

            for sym in SYMBOLS:
                if sym in open_pos:
                    continue
                if pos_count >= MAX_POSITIONS:
                    break

                time.sleep(1.5)  # v5.5: 1.5초 딜레이 (Rate Limit 방지)

                # 15분봉 지표
                df15 = get_ohlcv(sym, "15", 100)
                ind  = calc_indicators(df15)
                if not ind:
                    continue

                # 모드 판단
                m15 = detect_mode(ind)
                m1h = get_h1_mode(sym)
                fmode = get_final_mode(m15, m1h)

                # ── mode_history 기록 (심볼별) ──
                hist = mode_history.setdefault(sym, [])
                hist.append(fmode)
                if len(hist) > STABILITY_N + 5:
                    mode_history[sym] = hist[-(STABILITY_N + 5):]

                # ── 모드 변경 알림 ──
                old_mode = prev_mode.get(sym)
                if old_mode is not None and old_mode != fmode:
                    tg(f"📊 {sym}: {old_mode} → {fmode}")
                prev_mode[sym] = fmode

                # 관망 조건
                if fmode == "watch":
                    continue

                # 쿨다운 체크
                if cooldown.get(fmode, 0) > 0:
                    continue

                # ── 안정성 필터: 최근 STABILITY_N회 연속 같은 모드인지 확인 ──
                if not is_stable_mode(sym, fmode):
                    continue

                # ── 전략 ON/OFF 체크 ──
                if not strategy_enabled.get(fmode, True):
                    continue

                # 방향 카운트 체크
                long_cnt  = sum(1 for p in open_pos.values() if p["side"] == "Buy")
                short_cnt = sum(1 for p in open_pos.values() if p["side"] == "Sell")

                # ── 강한 추세 전략 진입 ──
                if fmode == "strong_trend":
                    sig = get_strong_trend_signal(ind)
                    if sig == "NONE":
                        continue
                    order_side = "Buy" if sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    # v5.5 동적비중
                    if DYN_SIZE_ENABLED:
                        adx_v = ind.get("adx", 28)
                        if adx_v >= 50:   act_size = min(ST_SIZE_PCT * 1.25, 0.40)
                        elif adx_v >= 35: act_size = ST_SIZE_PCT
                        else:             act_size = ST_SIZE_PCT * 0.78
                    else:
                        act_size = ST_SIZE_PCT

                    qty = calc_qty(balance, act_size, ind["price"], sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty)
                    if ok:
                        entry_times[sym] = time.time()
                        positions[sym] = {
                            "mode":            "strong_trend",
                            "side":            order_side,
                            "entry":           ind["price"],
                            "size":            qty,
                            "peak":            0,
                            "pyr_count":       0,
                            "last_pyr_price":  ind["price"],
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": ind["price"], "pnl": 0}
                        margin = balance * act_size
                        tg(f"""📈 {sym} 진입 [{sig}]
모드: 강한추세
가격: ${ind['price']:,.2f}
비중: {act_size*100:.0f}% (${margin:,.0f})
ADX: {ind['adx']:.1f} | BB폭: {ind['bb_width']*100:.2f}%
손절: -{ST_SL_PCT*100:.1f}% | 트레일활성: +{ST_TRAIL_ACT*100:.1f}%""")

                # ── 횡보 전략 진입 ──
                elif fmode == "sideways":
                    sig = get_sideways_signal(ind)
                    if sig == "NONE":
                        continue
                    order_side = "Buy" if sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    qty = calc_qty(balance, SW_SIZE_PCT, ind["price"], sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty)
                    if ok:
                        entry_times[sym] = time.time()
                        positions[sym] = {
                            "mode":            "sideways",
                            "side":            order_side,
                            "entry":           ind["price"],
                            "size":            qty,
                            "peak":            0,
                            "pyr_count":       0,
                            "last_pyr_price":  ind["price"],
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": ind["price"], "pnl": 0}
                        margin = balance * SW_SIZE_PCT
                        sig_kr = "BB상단→숏" if sig == "SHORT" else "BB하단→롱"
                        tg(f"""↔️ {sym} 진입 [{sig_kr}]
모드: 횡보
가격: ${ind['price']:,.2f}
비중: {SW_SIZE_PCT*100:.0f}% (${margin:,.0f})
BB위치: {ind['bb_pos']*100:.0f}% | RSI: {ind['rsi']:.0f}
익절: +{SW_TP_PCT*100:.1f}% | 손절: -{SW_SL_PCT*100:.1f}%""")

                # ── 약한추세 전략 진입 (v5.5) ──
                elif fmode == "weak_trend" and WEAK_ENABLED:
                    sig = get_strong_trend_signal(ind)  # 동일 신호 로직 재사용
                    if sig == "NONE":
                        continue
                    order_side = "Buy" if sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    qty = calc_qty(balance, WEAK_SIZE_PCT, ind["price"], sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty)
                    if ok:
                        entry_times[sym] = time.time()
                        positions[sym] = {
                            "mode":            "weak_trend",
                            "side":            order_side,
                            "entry":           ind["price"],
                            "size":            qty,
                            "peak":            0,
                            "pyr_count":       0,
                            "last_pyr_price":  ind["price"],
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": ind["price"], "pnl": 0}
                        margin = balance * WEAK_SIZE_PCT
                        tg(f"""〰️ {sym} 진입 [약한추세/{sig}]
모드: 약한추세
가격: ${ind['price']:,.2f}
비중: {WEAK_SIZE_PCT*100:.0f}% (${margin:,.0f})
ADX: {ind['adx']:.1f} | BB폭: {ind['bb_width']*100:.2f}%
익절: +{WEAK_TP_PCT*100:.1f}% | 손절: -{WEAK_SL_PCT*100:.1f}%""")

            # ── 정각 리포트 ──
            now_dt = datetime.now(KST)
            if now_dt.minute == 0 and now_dt.second < 25:
                now_ts = time.time()
                if now_ts - last_report >= 3500:  # 중복 방지
                    last_report = now_ts
                    open_pos = get_open_positions()
                    balance  = get_balance()
                    monthly_pnl = (balance - monthly_start) / monthly_start * 100 if monthly_start > 0 else 0

                    pos_lines = ""
                    for sym, p in open_pos.items():
                        side_kr = "롱" if p["side"] == "Buy" else "숏"
                        pos_lines += f"\n  {sym} {side_kr} PnL: ${p['pnl']:+.2f}"

                    # 전략별 성과
                    stats_lines = ""
                    mode_kr = {"strong_trend":"강한추세","sideways":"횡보","weak_trend":"약한추세"}
                    for m, kr in mode_kr.items():
                        st = trade_stats.get(m, {})
                        w = st.get("wins", 0); l = st.get("losses", 0); tot = w + l
                        if tot > 0:
                            wr = w / tot * 100
                            pnl_sum = st.get("total_pnl", 0)
                            stats_lines += f"\n  {kr}: {tot}회 승률{wr:.0f}% 누적${pnl_sum:+.1f}"

                    tg(f"""📊 {now_dt.strftime('%H:%M')} 리포트
잔고: ${balance:,.2f}
월 손익: {monthly_pnl:+.1f}%
포지션: {len(open_pos)}개{pos_lines}
쿨다운: 추세={cooldown['strong_trend']} 횡보={cooldown['sideways']}
─────────────────
전략별 성과 (이번달){stats_lines if stats_lines else chr(10)+"  기록 없음"}""")

            time.sleep(LOOP_SEC)

        except KeyboardInterrupt:
            tg("🛑 봇 수동 종료")
            sys.exit(0)
        except Exception as e:
            err = traceback.format_exc()
            print(f"[루프 오류] {e}")
            print(err)
            tg(f"⚠️ 봇 오류 발생\n{str(e)[:200]}")
            time.sleep(60)

# ══════════════════════════════════════════════════
# 엔트리포인트
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("❌ BYBIT_API_KEY / BYBIT_API_SECRET 환경변수 필요")
        sys.exit(1)

    print(f"""
╔══════════════════════════════════════╗
║   바이비트 봇 v5.5                    ║
║   3모드 전략 (추세/횡보/관망)           ║
║   BTC + ETH + SOL                    ║
╚══════════════════════════════════════╝
심볼: {SYMBOLS}
레버리지: {LEVERAGE}배
강한추세: 비중{ST_SIZE_PCT*100:.0f}% 손절{ST_SL_PCT*100:.1f}% 트레일+{ST_TRAIL_ACT*100:.1f}%
횡보:     비중{SW_SIZE_PCT*100:.0f}% 익절{SW_TP_PCT*100:.1f}% 손절{SW_SL_PCT*100:.1f}%
월한도:   -{MONTHLY_MAX_LOSS*100:.0f}%
""")

    init_session()
    run_loop()

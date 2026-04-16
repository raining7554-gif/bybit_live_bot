"""
바이비트 선물 실전 봇 v6.1
══════════════════════════════════════════════════
심볼: BTCUSDT / ETHUSDT (집중 운용)
레버리지: 12배

[v6.0 변경] BTC+ETH 2종목 집중, 50% 사이즈, 12x, 피라미딩 OFF
[v6.1 변경] 트레일 하향(0.5%), di_gap 버그수정, 코인별ADX, BB익절70%, 피라미딩상한60%

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
import os, sys, traceback, json
import requests
import pytz

sys.stdout.reconfigure(line_buffering=True)
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
SYMBOLS       = ["BTCUSDT", "ETHUSDT"]  # v6.0: BTC+ETH 집중
LEVERAGE      = int(os.environ.get("LEVERAGE", "12"))  # v6.0: 12배
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "2"))  # v6.0: BTC+ETH 2개
MAX_SAME_DIR  = int(os.environ.get("MAX_SAME_DIR", "2"))  # v6.0: 동방향 2개
LOOP_SEC      = 30  # v6.0: 30초 루프 (Rate Limit 강화 방지)
MIN_HOLD_SEC  = 180

# ── 시장 판단 기준 (환경변수로 에이전트가 조정 가능) ──
ADX_STRONG    = float(os.environ.get("ADX_STRONG",    "28"))    # 강한추세 기준
ADX_SIDEWAYS  = float(os.environ.get("ADX_SIDEWAYS",  "20"))    # 횡보 기준
BB_STRONG     = float(os.environ.get("BB_STRONG",     "0.015")) # 강한추세 BB폭 (v5.5: 1.5%로 완화)
BB_SIDEWAYS   = float(os.environ.get("BB_SIDEWAYS",   "0.022")) # 횡보 BB폭
DI_GAP        = float(os.environ.get("DI_GAP",        "10"))    # DI+/- 최소 갭
ATR_VOL_MULT  = float(os.environ.get("ATR_VOL_MULT",  "1.8"))   # 고변동성 배수

# ── 강한 추세 전략 파라미터 (v5.1 최적화) ──────────
ST_SIZE_PCT   = 0.50  # v6.0: 하드코딩 (Railway 환경변수 무시)
ST_SL_PCT     = float(os.environ.get("ST_SL_PCT",     "0.008")) # 손절 -0.8% (↑0.7%)
ST_TRAIL_ACT  = float(os.environ.get("ST_TRAIL_ACT",  "0.012")) # 트레일 활성 +1.2%
ST_TRAIL_CB   = float(os.environ.get("ST_TRAIL_CB",   "0.004")) # 트레일 콜백 0.4%

# ── 횡보 전략 파라미터 (v5.1 최적화) ──────────────
SW_SIZE_PCT   = 0.35  # v6.0: 하드코딩 (Railway 환경변수 무시)
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
WEAK_SIZE_PCT = 0.30  # v6.1: 30% (SIDEWAYS off 보완, 하드코딩)
WEAK_TP_PCT   = float(os.environ.get("WEAK_TP_PCT",   "0.008"))  # 익절 +0.8%
WEAK_SL_PCT   = float(os.environ.get("WEAK_SL_PCT",   "0.005"))  # 손절 -0.5%
WEAK_TRAIL_ACT= float(os.environ.get("WEAK_TRAIL_ACT","0.005"))  # 트레일 활성 +0.5%
WEAK_TRAIL_CB = float(os.environ.get("WEAK_TRAIL_CB", "0.002"))  # 트레일 콜백 0.2%
ADX_WEAK_MIN  = float(os.environ.get("ADX_WEAK_MIN",  "20"))     # 약한추세 ADX 최소
ADX_WEAK_MAX  = float(os.environ.get("ADX_WEAK_MAX",  "32"))     # 약한추세 ADX 최대

# ── v5.5 추가: 피라미딩 ──
PYR_ENABLED   = os.environ.get("PYR_ENABLED", "false").lower() == "true"  # v6.0: 12x 청산위험으로 OFF
PYR_TRIGGER   = float(os.environ.get("PYR_TRIGGER",  "0.020"))  # 기존 호환용 (미사용)
PYR_SIZE_PCT  = float(os.environ.get("PYR_SIZE_PCT",  "0.10"))   # 기존 호환용 (미사용)
PYR_MAX       = int(os.environ.get("PYR_MAX", "2"))
# ── v5.8: 2단계 피라미딩 세분화 ──
PYRAMID_STEP1 = float(os.environ.get("PYRAMID_STEP1", "0.01"))  # +1% 시 1차 추가
PYRAMID_STEP2 = float(os.environ.get("PYRAMID_STEP2", "0.03"))  # +3% 시 2차 추가
PYRAMID_SIZE1 = float(os.environ.get("PYRAMID_SIZE1", "0.15"))  # 1차 추가비중 15%
PYRAMID_SIZE2 = float(os.environ.get("PYRAMID_SIZE2", "0.20"))  # 2차 추가비중 20%

# ── v5.5 추가: 동적비중 ──
DYN_SIZE_ENABLED = os.environ.get("DYN_SIZE_ENABLED", "true").lower() == "true"

# ── v5.6 추가: BTC 진입 빈도 제한 ──
BTC_COOLDOWN_SEC = int(os.environ.get("BTC_COOLDOWN_SEC", "1800"))  # 기본 30분

# ── v5.6 추가: 숏 조건 강화 ──
SHORT_STRICT_MODE  = os.environ.get("SHORT_STRICT_MODE", "true").lower() == "true"
ADX_SHORT_STRONG   = float(os.environ.get("ADX_SHORT_STRONG",  "35"))   # 강한추세 숏 ADX 최소
BB_POS_SHORT       = float(os.environ.get("BB_POS_SHORT",      "0.92")) # 횡보 숏 BB 위치
RSI_SHORT_SW       = float(os.environ.get("RSI_SHORT_SW",      "65"))   # 횡보 숏 RSI 최소

# ── v5.6 추가: Limit 주문 ──
USE_LIMIT_ORDER    = os.environ.get("USE_LIMIT_ORDER", "true").lower() == "true"
LIMIT_OFFSET_ATR   = float(os.environ.get("LIMIT_OFFSET_ATR",  "0.1"))  # ATR * 0.1 offset
LIMIT_TIMEOUT_SEC  = int(os.environ.get("LIMIT_TIMEOUT_SEC",   "30"))   # 30초 미체결 취소

# ── v5.7 추가: ATR 기반 동적 손절 ──
SL_ATR_MULT    = float(os.environ.get("SL_ATR_MULT",   "1.5"))   # ATR × 1.5
SL_ATR_MIN     = float(os.environ.get("SL_ATR_MIN",    "0.005")) # 최소 손절 -0.5%
SL_ATR_MAX     = float(os.environ.get("SL_ATR_MAX",    "0.015")) # 최대 손절 -1.5%

# ── v5.7 추가: 횡보 BB 기반 익절 ──
SW_TP_MIN      = float(os.environ.get("SW_TP_MIN",     "0.008")) # 최소 익절 +0.8%
SW_TP_MAX      = float(os.environ.get("SW_TP_MAX",     "0.020")) # 최대 익절 +2.0%

# ── v5.7 추가: 약한추세 관망 옵션 ──
WEAK_TREND_ENABLED = os.environ.get("WEAK_TREND_ENABLED", "false").lower() == "true"

# ── v5.7 추가: 시간대 필터 ──
QUIET_HOURS_ENABLED = os.environ.get("QUIET_HOURS_ENABLED", "true").lower() == "true"
QUIET_HOURS_START   = int(os.environ.get("QUIET_HOURS_START", "9"))   # UTC 시작
QUIET_HOURS_END     = int(os.environ.get("QUIET_HOURS_END",   "13"))  # UTC 종료

# ── v5.8 추가: 눌림목 진입 ──
PULLBACK_MODE       = os.environ.get("PULLBACK_MODE", "true").lower() == "true"
PULLBACK_BAND       = float(os.environ.get("PULLBACK_BAND", "0.005"))  # EMA20 ±0.5%

# ── v5.8 추가: 롱/숏 비대칭 비중 ──
LONG_SIZE_MULT      = float(os.environ.get("LONG_SIZE_MULT",  "1.15"))
SHORT_SIZE_MULT     = float(os.environ.get("SHORT_SIZE_MULT", "0.75"))

# ── v5.8 추가: 강한추세 손절 후 재진입 ──
STRONG_REENTRY_MIN  = int(os.environ.get("STRONG_REENTRY_MIN", "20"))  # 재진입 대기 분

# ── v5.8 추가: 거래량 필터 ──
VOLUME_MIN_STRONG   = float(os.environ.get("VOLUME_MIN_STRONG", "1.2"))  # vol_ratio 최소

# ── v5.8 추가: 히스테리시스 임계 ──
ADX_STRONG_HOLD     = float(os.environ.get("ADX_STRONG_HOLD",  "25"))   # 강한추세 유지 ADX
ADX_SIDEWAYS_HOLD   = float(os.environ.get("ADX_SIDEWAYS_HOLD","23"))   # 횡보 유지 ADX

# ══════════════════════════════════════════════════
# 코인별 파라미터 (기능 A)
# ══════════════════════════════════════════════════
SYMBOL_CONFIG = {
    "BTCUSDT": {
        "sl_atr_mult":  1.3,
        "sl_min":       0.005,
        "sl_max":       0.012,
        "volume_min":   1.3,
        "adx_strong":   30,
        "cooldown_sec": 1800,
    },
    "ETHUSDT": {
        "sl_atr_mult":  1.5,
        "sl_min":       0.005,
        "sl_max":       0.015,
        "volume_min":   1.2,
        "adx_strong":   28,
        "cooldown_sec": 600,
    },
    "SOLUSDT": {
        "sl_atr_mult":  1.8,
        "sl_min":       0.006,
        "sl_max":       0.018,
        "volume_min":   1.15,
        "adx_strong":   26,
        "cooldown_sec": 600,
    },
    "XRPUSDT": {
        "sl_atr_mult":  1.8,
        "sl_min":       0.006,
        "sl_max":       0.018,
        "volume_min":   1.15,
        "adx_strong":   26,
        "cooldown_sec": 600,
    },
    "LINKUSDT": {
        "sl_atr_mult":  1.5,
        "sl_min":       0.005,
        "sl_max":       0.015,
        "volume_min":   1.2,
        "adx_strong":   28,
        "cooldown_sec": 600,
    },
}

def get_sym_cfg(symbol: str) -> dict:
    """코인별 파라미터 반환, 없으면 ETHUSDT 기본값"""
    return SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["ETHUSDT"])

# ══════════════════════════════════════════════════
# 거래 기록 / 메트릭 (기능 B)
# ══════════════════════════════════════════════════
TRADE_LOG_PATH = "/tmp/trades.jsonl"

def log_trade(symbol: str, mode: str, side: str, entry: float,
              exit_price: float, pnl: float, pnl_pct: float, reason: str):
    """거래 종료 시 JSONL 파일에 기록"""
    rec = {
        "ts":       time.time(),
        "symbol":   symbol,
        "mode":     mode,
        "side":     side,
        "entry":    entry,
        "exit":     exit_price,
        "pnl":      round(pnl, 4),
        "pnl_pct":  round(pnl_pct, 6),
        "reason":   reason,
    }
    try:
        with open(TRADE_LOG_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[로그 오류] {e}")

def compute_metrics(days: int = 7) -> dict:
    """최근 N일 거래 통계 계산: 승률, 샤프, MDD, 코인별 손익"""
    cutoff = time.time() - days * 86400
    trades = []
    try:
        with open(TRADE_LOG_PATH) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("ts", 0) >= cutoff:
                        trades.append(rec)
                except Exception:
                    pass
    except FileNotFoundError:
        return {}

    if not trades:
        return {}

    pnls     = [t["pnl"] for t in trades]
    wins     = sum(1 for p in pnls if p >= 0)
    total    = len(pnls)
    win_rate = wins / total if total else 0.0

    # 샤프: 일별 PnL 집계 후 연율화
    by_day: dict = {}
    for t in trades:
        day = int(t["ts"] // 86400)
        by_day[day] = by_day.get(day, 0.0) + t["pnl"]
    daily = list(by_day.values())
    if len(daily) >= 2:
        mu     = np.mean(daily)
        std    = np.std(daily, ddof=1)
        sharpe = (mu / std * np.sqrt(365)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    # MDD: 누적 PnL 기준
    cumulative = np.cumsum(pnls)
    peak       = np.maximum.accumulate(cumulative)
    mdd        = float(np.max(peak - cumulative)) if len(cumulative) > 0 else 0.0

    # 코인별 손익
    sym_pnl: dict = {}
    for t in trades:
        s = t["symbol"]
        sym_pnl[s] = sym_pnl.get(s, 0.0) + t["pnl"]

    return {
        "total":     total,
        "wins":      wins,
        "win_rate":  win_rate,
        "sharpe":    round(sharpe, 2),
        "mdd":       round(mdd, 2),
        "total_pnl": round(sum(pnls), 2),
        "sym_pnl":   sym_pnl,
    }

# ── v5.5 추가: 단계별 트레일 ──
# TRAIL_LEVELS: 실제 가격% 기준 (레버리지 반영)
# 레버리지 10배 기준: 레버수익% / 10 = 실제가격%
# v5.5b: 타이트하게 조임 → 수익 더 빨리 보호
TRAIL_LEVELS = [
    (0.005, 0.0015),  # 실제+0.5%(레버6%)  → 콜백 0.15% (v6.1: 빠른 수익 보호)
    (0.010, 0.003),   # 실제+1.0%(레버12%) → 콜백 0.3%  (v6.1: 하향)
    (0.020, 0.005),   # 실제+2.0%(레버24%) → 콜백 0.5%
    (0.030, 0.008),   # 실제+3.0%(레버36%) → 콜백 0.8%
    (0.055, 0.015),   # 실제+5.5%(레버66%) → 콜백 1.5%
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
last_exit      = {}    # {symbol: float} 마지막 청산 시각 (코인별 쿨다운용)
pending_orders = {}    # {symbol: {"order_id": str, "placed_at": float}} Limit 미체결 추적
strong_sl_time = {}    # {symbol: float} 강한추세 손절 시각 (재진입 쿨다운용)

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
                elif text.strip() == "/stats":
                    m7 = compute_metrics(7)
                    if not m7:
                        tg("/stats: 최근 7일 거래 기록 없음")
                    else:
                        sym_lines = "".join(
                            f"\n  {s}: ${v:+.2f}"
                            for s, v in sorted(m7["sym_pnl"].items(), key=lambda x: -x[1])
                        )
                        tg(f"""📊 /stats (최근 7일)
거래: {m7['total']}회 | 승률: {m7['win_rate']*100:.0f}%
누적 PnL: ${m7['total_pnl']:+.2f}
MDD: ${m7['mdd']:.2f}
샤프: {m7['sharpe']:.2f}
코인별:{sym_lines}""")
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
        api_secret=API_SECRET,
        max_retries=3,   # v6.0: pybit 내부 재시도 끔 (rate limit 루프 방지)
        retry_delay=5    # v6.0: 재시도 간격 5초
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

_last_balance = 0.0  # v6.1: 잔고 조회 실패 대비

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

def place_order(symbol: str, side: str, qty: float, atr: float = 0.0) -> bool:
    """진입 주문: USE_LIMIT_ORDER=true면 ATR 기반 Limit, 아니면 Market"""
    try:
        if USE_LIMIT_ORDER and atr > 0:
            price = get_price(symbol)
            if price <= 0:
                return False
            offset = atr * LIMIT_OFFSET_ATR
            # 롱: 현재가보다 약간 아래, 숏: 약간 위
            limit_price = price - offset if side == "Buy" else price + offset
            # 심볼별 소수점 처리 (가격)
            price_decimals = {"BTCUSDT": 1, "ETHUSDT": 2, "SOLUSDT": 3,
                              "XRPUSDT": 4, "LINKUSDT": 3}
            pd_ = price_decimals.get(symbol, 2)
            limit_price = round(limit_price, pd_)
            # v6.1: 서버사이드 재해 스톱 (-2% 가격, 봇 죽어도 동작)
            sl_price = limit_price * (0.98 if side == "Buy" else 1.02)
            sl_price = round(sl_price, pd_)
            r = session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Limit",
                qty=str(qty),
                price=str(limit_price),
                timeInForce="GTC",
                positionIdx=_get_position_idx(side),
                stopLoss=str(sl_price),
            )
            if r["retCode"] == 0:
                order_id = r["result"].get("orderId", "")
                pending_orders[symbol] = {
                    "order_id":  order_id,
                    "placed_at": time.time(),
                }
                return True
            return False
        else:
            # v6.1: Market 진입 + 서버사이드 재해 스톱
            mk_price = get_price(symbol)
            price_decimals = {"BTCUSDT": 1, "ETHUSDT": 2, "SOLUSDT": 3,
                              "XRPUSDT": 4, "LINKUSDT": 3}
            pd_ = price_decimals.get(symbol, 2)
            sl_price = mk_price * (0.98 if side == "Buy" else 1.02) if mk_price > 0 else 0
            sl_price = round(sl_price, pd_) if sl_price > 0 else 0
            kwargs = dict(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                positionIdx=_get_position_idx(side),
            )
            if sl_price > 0:
                kwargs["stopLoss"] = str(sl_price)
            r = session.place_order(**kwargs)
            return r["retCode"] == 0
    except Exception as e:
        print(f"[주문 오류 {symbol}] {e}")
        return False

def cancel_stale_orders():
    """LIMIT_TIMEOUT_SEC 초과 미체결 Limit 주문 취소"""
    now = time.time()
    stale = [sym for sym, o in pending_orders.items()
             if now - o["placed_at"] >= LIMIT_TIMEOUT_SEC]
    for sym in stale:
        order_id = pending_orders[sym]["order_id"]
        try:
            session.cancel_order(category="linear", symbol=sym, orderId=order_id)
            print(f"[Limit 취소] {sym} orderId={order_id}")
            tg(f"⏱ {sym} Limit 주문 미체결 취소 (30초 초과)")
        except Exception as e:
            print(f"[주문 취소 오류 {sym}] {e}")
        pending_orders.pop(sym, None)

def close_position(symbol: str, pos: dict) -> bool:
    close_side = "Sell" if pos["side"] == "Buy" else "Buy"
    # 청산은 항상 Market (빠른 청산)
    try:
        r = session.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(pos["size"]),
            positionIdx=_get_position_idx(close_side),
        )
        return r["retCode"] == 0
    except Exception as e:
        print(f"[청산 오류 {symbol}] {e}")
        return False

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
def detect_mode(ind: dict, current_mode: str = "", symbol: str = "") -> str:
    """
    strong_trend : 강한 추세 → 추세 추종 전략
    sideways     : 횡보      → BB 역추세 전략
    high_vol     : 고변동성  → 관망
    unclear      : 애매      → 관망
    v5.8: current_mode 파라미터로 히스테리시스 적용
    v6.1: symbol 파라미터로 코인별 ADX 임계값 적용
    """
    if not ind:
        return "unclear"

    # v6.1: 코인별 ADX_STRONG 임계값
    sym_adx_strong = get_sym_cfg(symbol)["adx_strong"] if symbol else ADX_STRONG

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

    # ── 히스테리시스: 현재 모드 유지 임계 ──
    # 강한추세 유지: 진입 ADX>28, 이탈은 ADX<25 (ADX_STRONG_HOLD)
    if current_mode == "strong_trend":
        if adx >= ADX_STRONG_HOLD and bb_width > BB_STRONG and di_gap > DI_GAP:
            return "strong_trend"
    # 횡보 유지: 진입 ADX<20, 이탈은 ADX>23 (ADX_SIDEWAYS_HOLD)
    # v6.1: SIDEWAYS 히스테리시스 비활성
    if False and current_mode == "sideways":
        if adx <= ADX_SIDEWAYS_HOLD and 0.015 < bb_width < BB_SIDEWAYS:
            return "sideways"

    # 강한 추세 신규 진입 (v6.1: 코인별 ADX 임계값)
    if adx > sym_adx_strong and bb_width > BB_STRONG and di_gap > DI_GAP:
        return "strong_trend"

    # 횡보: ADX 낮고 BB 좁지만 최소 1.5% 이상이어야 진입 의미있음
    # v6.1: SIDEWAYS 신규 진입 비활성 (WEAK가 커버)
    if False and adx < ADX_SIDEWAYS and 0.015 < bb_width < BB_SIDEWAYS:
        return "sideways"

    # 약한추세 (v5.5): ADX 20~32, 방향성 있지만 강하지 않은 구간
    # v6.1: di_gap 중복 계산 버그 수정 (L768에서 이미 계산됨)
    if ADX_WEAK_MIN <= adx <= ADX_WEAK_MAX and di_gap > 6 and WEAK_ENABLED:
        return "weak_trend"

    return "unclear"

def get_h1_mode(symbol: str) -> tuple:
    """1시간봉 모드 + 지표 캐시 (15분마다 갱신). (mode, ind1h) 반환"""
    now = time.time()
    if symbol in h1_cache:
        cached_mode, cached_time, cached_ind = h1_cache[symbol]
        if now - cached_time < H1_CACHE_SEC:
            return cached_mode, cached_ind

    df1h = get_ohlcv(symbol, "60", 80)
    ind1h = calc_indicators(df1h)
    mode = detect_mode(ind1h)
    h1_cache[symbol] = (mode, now, ind1h)
    return mode, ind1h

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

def get_pullback_signal(ind15: dict, ind1h: dict) -> str:
    """
    눌림목 진입 신호 (PULLBACK_MODE=true 시 사용)
    - 1H EMA20 > EMA50 (상승 추세) + 15m 가격이 EMA20 ±0.5% 이내 → LONG
    - 1H EMA20 < EMA50 (하락 추세) + 15m 가격이 EMA20 ±0.5% 이내 → SHORT
    - ADX 조건 불필요 (조정 구간이므로 ADX 낮아도 허용)
    """
    if not ind15 or not ind1h:
        return "NONE"
    price    = ind15["price"]
    ema20_15 = ind15["ema20"]
    ema20_1h = ind1h.get("ema20", 0)
    ema50_1h = ind1h.get("ema50", 0)
    if ema20_15 <= 0 or ema20_1h <= 0:
        return "NONE"

    near_ema = abs(price - ema20_15) / ema20_15 <= PULLBACK_BAND

    if not near_ema:
        return "NONE"

    h1_uptrend   = ema20_1h > ema50_1h
    h1_downtrend = ema20_1h < ema50_1h

    # 추가 필터: RSI 과열/과매도 제외
    if h1_uptrend   and ind15["rsi"] < 65:
        return "LONG"
    if h1_downtrend and ind15["rsi"] > 35 and not SHORT_STRICT_MODE:
        return "SHORT"
    if h1_downtrend and ind15["rsi"] > 35 and SHORT_STRICT_MODE and ind15["adx"] >= ADX_SHORT_STRONG:
        return "SHORT"
    return "NONE"

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
    # SHORT_STRICT_MODE: 숏은 ADX_SHORT_STRONG(35) 이상일 때만 허용
    adx_short_ok = ind["adx"] >= ADX_SHORT_STRONG if SHORT_STRICT_MODE else True
    short_ok = ema_short and di_short and ind["rsi"] > 32 and adx_short_ok

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

    # BB 상단 → 숏 (v6.1: 0.88→0.85, RSI 60→58 완화)
    bb_short_thr = BB_POS_SHORT if SHORT_STRICT_MODE else 0.85
    rsi_short_thr = RSI_SHORT_SW if SHORT_STRICT_MODE else 58
    if ind["bb_pos"] > bb_short_thr and ind["rsi"] > rsi_short_thr:
        if sum([vw, uw, rdt]) >= 2:
            return "SHORT"

    # BB 하단 → 롱 (v6.1: 0.12→0.15, RSI 40→42 완화)
    if ind["bb_pos"] < 0.15 and ind["rsi"] < 42:
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

    # ── 강한 추세 청산 (v5.7: ATR 동적 손절 + 단계별 트레일) ──
    if mode == "strong_trend":
        # ATR 기반 동적 손절: 진입 시 저장한 sl_pct 사용, 없으면 ST_SL_PCT 폴백
        sl_pct = pos.get("sl_pct", ST_SL_PCT)
        if pnl_pct <= -sl_pct:
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
        # BB 기반 동적 익절: 진입 시 저장한 tp_pct 사용, 없으면 SW_TP_PCT 폴백
        tp_pct = pos.get("tp_pct", SW_TP_PCT)
        if pnl_pct >= tp_pct:
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
# 시간대 필터
# ══════════════════════════════════════════════════
def is_quiet_hours() -> bool:
    """UTC 기준 QUIET_HOURS_START~END 시간대이면 True"""
    if not QUIET_HOURS_ENABLED:
        return False
    utc_hour = datetime.now(timezone.utc).hour
    if QUIET_HOURS_START <= QUIET_HOURS_END:
        return QUIET_HOURS_START <= utc_hour < QUIET_HOURS_END
    # 자정 걸치는 경우 (예: 22~02)
    return utc_hour >= QUIET_HOURS_START or utc_hour < QUIET_HOURS_END

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
    global monthly_start, monthly_stop, mode_history, prev_mode, last_exit, strong_sl_time

    loop_count = 0
    last_report = time.time()
    REPORT_SEC = 3600  # 1시간마다 리포트

    tg(f"""🚀 바이비트 봇 v6.0 시작 (BTC+ETH 집중)
심볼: {', '.join(SYMBOLS)}
레버리지: {LEVERAGE}배
최대포지션: {MAX_POSITIONS}
포지션모드: {POSITION_MODE}
전략: 3모드 (강한추세/횡보/관망)
추세: 비중{ST_SIZE_PCT*100:.0f}% 손절{ST_SL_PCT*100:.1f}% 트레일5단계
횡보: 비중{SW_SIZE_PCT*100:.0f}% 익절{SW_TP_PCT*100:.1f}%
약한추세: {"ON" if WEAK_ENABLED else "OFF"} (비중{WEAK_SIZE_PCT*100:.0f}% 익절{WEAK_TP_PCT*100:.1f}%)
피라미딩: {"ON" if PYR_ENABLED else "OFF"}
동적비중: {"ON" if DYN_SIZE_ENABLED else "OFF"}
테스트넷: {TESTNET}""")

    while True:
        try:
            loop_count += 1
            update_cooldown()

            # ── 텔레그램 업데이트 폴링 ──
            poll_telegram_updates()

            global _last_balance  # v6.1
            balance = get_balance()
            if balance <= 0:
                if _last_balance > 0:
                    balance = _last_balance
                    print(f"[경고] 잔고 조회 실패 → 마지막 정상값 사용: {balance:.2f}")
                else:
                    time.sleep(LOOP_SEC)
                    continue
            else:
                _last_balance = balance

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

                # ── v6.1 피라미딩 (2단계 세분화 + 총비중 상한 60%) ──
                if PYR_ENABLED and not reason:
                    # v6.1: 총 비중 상한 체크
                    total_notional = sum(
                        p.get("size", 0) * get_price(s)
                        for s, p in open_pos.items()
                    )
                    max_notional = balance * 0.60 * LEVERAGE
                    pyr_allowed = total_notional < max_notional

                    entry_p = local_pos.get("entry", price)
                    side    = local_pos.get("side", "Buy")
                    cur_pnl = (price - entry_p) / entry_p if side == "Buy" else (entry_p - price) / entry_p
                    pyr_s1  = local_pos.get("pyr_s1", False)  # 1차 추가 완료 여부
                    pyr_s2  = local_pos.get("pyr_s2", False)  # 2차 추가 완료 여부
                    pyr_side = side  # Buy or Sell

                    def _do_pyramid(size_pct: float, step_label: str):
                        qty2 = calc_qty(balance, size_pct, price, sym)
                        if qty2 <= 0:
                            return
                        try:
                            session.place_order(
                                category="linear", symbol=sym,
                                side=pyr_side,
                                orderType="Market", qty=str(qty2),
                                positionIdx=_get_position_idx(pyr_side),
                            )
                            tg(f"📈 {sym} 피라미딩 {step_label}\n"
                               f"수익: {cur_pnl*100:+.2f}% → 추가비중 {size_pct*100:.0f}%")
                        except Exception as e:
                            print(f"[피라미딩 오류] {e}")

                    # 1차: +1% 도달 시 (v6.1: pyr_allowed 체크)
                    if pyr_allowed and not pyr_s1 and cur_pnl >= PYRAMID_STEP1:
                        _do_pyramid(PYRAMID_SIZE1, "#1(+1%→+15%)")
                        local_pos["pyr_s1"] = True
                    # 2차: +3% 도달 시 (1차 완료 후)
                    elif pyr_allowed and pyr_s1 and not pyr_s2 and cur_pnl >= PYRAMID_STEP2:
                        _do_pyramid(PYRAMID_SIZE2, "#2(+3%→+20%)")
                        local_pos["pyr_s2"] = True

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
                        pending_orders.pop(sym, None)
                        last_exit[sym] = time.time()
                        log_trade(sym, mode, api_pos["side"], api_pos["entry"],
                                  price, pnl, pnl_pct, reason)
                        # 수정 5: 강한추세 손절 시각 기록 (재진입 쿨다운용)
                        if reason == "sl" and mode == "strong_trend":
                            strong_sl_time[sym] = time.time()

            # ── Limit 미체결 주문 정리 ──
            cancel_stale_orders()

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

                # 모드 판단 (히스테리시스: 이전 모드 전달)
                cur_sym_mode = prev_mode.get(sym, "")
                m15   = detect_mode(ind, current_mode=cur_sym_mode, symbol=sym)
                m1h, ind1h = get_h1_mode(sym)
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

                # ── 관망 구간에서도 눌림목 진입 시도 (PULLBACK_MODE) ──
                pullback_sig = "NONE"
                if fmode == "watch" and PULLBACK_MODE:
                    pullback_sig = get_pullback_signal(ind, ind1h)
                    if pullback_sig == "NONE":
                        continue
                elif fmode == "watch":
                    continue

                # 쿨다운 체크 (눌림목은 strong_trend 쿨다운 공유)
                check_mode = "strong_trend" if pullback_sig != "NONE" else fmode
                if cooldown.get(check_mode, 0) > 0:
                    continue

                # ── 안정성 필터: 눌림목은 안정성 필터 면제 (조정은 단기 현상) ──
                if pullback_sig == "NONE" and not is_stable_mode(sym, fmode):
                    continue

                # ── 전략 ON/OFF 체크 ──
                eff_mode = "strong_trend" if pullback_sig != "NONE" else fmode
                if not strategy_enabled.get(eff_mode, True):
                    continue

                # ── 코인별 진입 쿨다운 ──
                _sym_cd   = get_sym_cfg(sym)["cooldown_sec"]
                _sym_last = last_exit.get(sym, 0)
                if _sym_last > 0 and time.time() - _sym_last < _sym_cd:
                    remain = int(_sym_cd - (time.time() - _sym_last))
                    print(f"[{sym} 쿨다운] {remain}초 남음")
                    continue

                # ── Limit 미체결 주문 있으면 중복 진입 방지 ──
                if sym in pending_orders:
                    continue

                # ── 시간대 필터 ──
                if is_quiet_hours():
                    continue

                # 방향 카운트 체크
                long_cnt  = sum(1 for p in open_pos.values() if p["side"] == "Buy")
                short_cnt = sum(1 for p in open_pos.values() if p["side"] == "Sell")

                atr       = ind.get("atr", 0.0)
                price_now = ind["price"]

                # ── ATR 동적 손절 계산 (코인별 파라미터 적용) ──
                _scfg = get_sym_cfg(sym)
                if atr > 0 and price_now > 0:
                    dyn_sl_pct = max(_scfg["sl_min"], min(_scfg["sl_max"],
                                     (atr * _scfg["sl_atr_mult"]) / price_now))
                else:
                    dyn_sl_pct = ST_SL_PCT

                # ── BB 기반 동적 익절 계산 (횡보용) ──
                half_band  = ind["bb_mid"] * ind["bb_width"] / 2
                bb_up_val  = ind["bb_mid"] + half_band
                bb_low_val = ind["bb_mid"] - half_band

                def _apply_dir_mult(base_size: float, order_side: str) -> float:
                    """롱/숏 비대칭 비중 적용"""
                    mult = LONG_SIZE_MULT if order_side == "Buy" else SHORT_SIZE_MULT
                    return base_size * mult

                # ══════════════════════════════════════════════════
                # ── 눌림목 진입 (PULLBACK_MODE, fmode==watch 시) ──
                # ══════════════════════════════════════════════════
                if pullback_sig != "NONE":
                    order_side = "Buy" if pullback_sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    # 거래량 필터 (코인별)
                    if ind.get("vol_ratio", 1.0) < _scfg["volume_min"]:
                        continue

                    # 강한추세 손절 후 재진입 쿨다운 체크 (수정 5)
                    sl_ts = strong_sl_time.get(sym, 0)
                    if sl_ts > 0 and (time.time() - sl_ts) < STRONG_REENTRY_MIN * 60:
                        continue

                    base_size = ST_SIZE_PCT * 0.78  # 눌림목은 약간 보수적 비중
                    act_size  = _apply_dir_mult(base_size, order_side)
                    qty = calc_qty(balance, act_size, price_now, sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty, atr=atr)
                    if ok:
                        entry_times[sym]  = time.time()
                        positions[sym] = {
                            "mode":  "strong_trend",
                            "side":  order_side,
                            "entry": price_now,
                            "size":  qty,
                            "peak":  0,
                            "sl_pct": dyn_sl_pct,
                            "pyr_s1": False, "pyr_s2": False,
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": price_now, "pnl": 0}
                        order_type_str = "Limit" if USE_LIMIT_ORDER else "Market"
                        tg(f"""🎯 {sym} 눌림목 진입 [{pullback_sig}] ({order_type_str})
가격: ${price_now:,.2f} | EMA20 근처
비중: {act_size*100:.0f}% | 손절: -{dyn_sl_pct*100:.2f}%
ADX: {ind['adx']:.1f} | RSI: {ind['rsi']:.0f}""")

                # ══════════════════════════════════════════════════
                # ── 강한 추세 전략 진입 ──
                # ══════════════════════════════════════════════════
                elif fmode == "strong_trend":
                    sig = get_strong_trend_signal(ind)
                    if sig == "NONE":
                        continue
                    order_side = "Buy" if sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    # 수정 6: 거래량 필터 (코인별)
                    if ind.get("vol_ratio", 1.0) < _scfg["volume_min"]:
                        continue

                    # 수정 5: 강한추세 손절 후 재진입 쿨다운
                    sl_ts = strong_sl_time.get(sym, 0)
                    if sl_ts > 0 and (time.time() - sl_ts) < STRONG_REENTRY_MIN * 60:
                        continue

                    # 동적비중 (v5.5) + 비대칭 비중 (v5.8)
                    if DYN_SIZE_ENABLED:
                        adx_v = ind.get("adx", 28)
                        if adx_v >= 50:   base_size = min(ST_SIZE_PCT * 1.25, 0.60)  # v6.0 cap
                        elif adx_v >= 35: base_size = ST_SIZE_PCT
                        else:             base_size = ST_SIZE_PCT * 0.78
                    else:
                        base_size = ST_SIZE_PCT
                    act_size = _apply_dir_mult(base_size, order_side)

                    qty = calc_qty(balance, act_size, price_now, sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty, atr=atr)
                    if ok:
                        entry_times[sym] = time.time()
                        positions[sym] = {
                            "mode":   "strong_trend",
                            "side":   order_side,
                            "entry":  price_now,
                            "size":   qty,
                            "peak":   0,
                            "sl_pct": dyn_sl_pct,
                            "pyr_s1": False, "pyr_s2": False,
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": price_now, "pnl": 0}
                        margin = balance * act_size
                        order_type_str = "Limit" if USE_LIMIT_ORDER else "Market"
                        tg(f"""📈 {sym} 진입 [{sig}] ({order_type_str})
모드: 강한추세
가격: ${price_now:,.2f}
비중: {act_size*100:.0f}% (${margin:,.0f})
ADX: {ind['adx']:.1f} | BB폭: {ind['bb_width']*100:.2f}% | 거래량: {ind['vol_ratio']:.2f}
손절: -{dyn_sl_pct*100:.2f}% (ATR×{_scfg['sl_atr_mult']}) | 트레일활성: +{TRAIL_LEVELS[0][0]*100:.1f}%""")

                # ══════════════════════════════════════════════════
                # ── 횡보 전략 진입 ──
                # ══════════════════════════════════════════════════
                elif fmode == "sideways":
                    sig = get_sideways_signal(ind)
                    if sig == "NONE":
                        continue
                    order_side = "Buy" if sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    # BB 폭 기반 동적 비중 + 비대칭 비중
                    bb_w = ind["bb_width"]
                    if bb_w >= 0.020:
                        sw_base = min(SW_SIZE_PCT * 1.2, 0.42)  # v6.0 cap
                    elif bb_w >= 0.015:
                        sw_base = SW_SIZE_PCT
                    else:
                        continue
                    sw_act_size = _apply_dir_mult(sw_base, order_side)

                    # v6.1: BB 중간선까지 70% 거리로 동적 익절 (더 현실적)
                    if sig == "LONG":
                        raw_tp = (ind["bb_mid"] - price_now) / price_now * 0.70 if price_now > 0 else SW_TP_MIN
                    else:
                        raw_tp = (price_now - ind["bb_mid"]) / price_now * 0.70 if price_now > 0 else SW_TP_MIN
                    sw_tp = max(SW_TP_MIN, min(SW_TP_MAX, raw_tp))

                    qty = calc_qty(balance, sw_act_size, price_now, sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty, atr=atr)
                    if ok:
                        entry_times[sym] = time.time()
                        positions[sym] = {
                            "mode":   "sideways",
                            "side":   order_side,
                            "entry":  price_now,
                            "size":   qty,
                            "peak":   0,
                            "tp_pct": sw_tp,
                            "pyr_s1": False, "pyr_s2": False,
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": price_now, "pnl": 0}
                        margin = balance * sw_act_size
                        sig_kr = "BB상단→숏" if sig == "SHORT" else "BB하단→롱"
                        order_type_str = "Limit" if USE_LIMIT_ORDER else "Market"
                        tg(f"""↔️ {sym} 진입 [{sig_kr}] ({order_type_str})
모드: 횡보
가격: ${price_now:,.2f}
비중: {sw_act_size*100:.0f}% (${margin:,.0f})
BB위치: {ind['bb_pos']*100:.0f}% | RSI: {ind['rsi']:.0f}
익절: +{sw_tp*100:.2f}% (BB반대편) | 손절: -{SW_SL_PCT*100:.1f}%""")

                # ══════════════════════════════════════════════════
                # ── 약한추세 전략 진입 ──
                # ══════════════════════════════════════════════════
                elif fmode == "weak_trend" and WEAK_ENABLED and WEAK_TREND_ENABLED:
                    sig = get_strong_trend_signal(ind)
                    if sig == "NONE":
                        continue
                    if sig == "SHORT" and SHORT_STRICT_MODE:
                        continue
                    order_side = "Buy" if sig == "LONG" else "Sell"
                    if order_side == "Buy"  and long_cnt  >= MAX_SAME_DIR: continue
                    if order_side == "Sell" and short_cnt >= MAX_SAME_DIR: continue

                    act_size = _apply_dir_mult(WEAK_SIZE_PCT, order_side)
                    qty = calc_qty(balance, act_size, price_now, sym)
                    if qty <= 0:
                        continue

                    ok = place_order(sym, order_side, qty, atr=atr)
                    if ok:
                        entry_times[sym] = time.time()
                        positions[sym] = {
                            "mode":   "weak_trend",
                            "side":   order_side,
                            "entry":  price_now,
                            "size":   qty,
                            "peak":   0,
                            "pyr_s1": False, "pyr_s2": False,
                        }
                        pos_count += 1
                        open_pos[sym] = {"side": order_side, "size": qty, "entry": price_now, "pnl": 0}
                        margin = balance * act_size
                        order_type_str = "Limit" if USE_LIMIT_ORDER else "Market"
                        tg(f"""〰️ {sym} 진입 [약한추세/{sig}] ({order_type_str})
모드: 약한추세
가격: ${price_now:,.2f}
비중: {act_size*100:.0f}% (${margin:,.0f})
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

                    m7 = compute_metrics(7)
                    if m7:
                        metrics_line = (
                            f"\n─────────────────"
                            f"\n📈 7일 메트릭"
                            f"\n  거래: {m7['total']}회 | 승률: {m7['win_rate']*100:.0f}%"
                            f"\n  누적: ${m7['total_pnl']:+.1f} | MDD: ${m7['mdd']:.1f}"
                            f"\n  샤프: {m7['sharpe']:.2f}"
                        )
                    else:
                        metrics_line = ""
                    tg(f"""📊 {now_dt.strftime('%H:%M')} 리포트
잔고: ${balance:,.2f}
월 손익: {monthly_pnl:+.1f}%
포지션: {len(open_pos)}개{pos_lines}
쿨다운: 추세={cooldown['strong_trend']} 횡보={cooldown['sideways']}
─────────────────
전략별 성과 (이번달){stats_lines if stats_lines else chr(10)+"  기록 없음"}{metrics_line}""")

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
║   바이비트 봇 v6.0 (BTC+ETH 집중)     ║
║   3모드 전략 (추세/횡보/관망)           ║
║   BTC + ETH 12x / 50%                ║
╚══════════════════════════════════════╝
심볼: {SYMBOLS}
레버리지: {LEVERAGE}배
강한추세: 비중{ST_SIZE_PCT*100:.0f}% 손절{ST_SL_PCT*100:.1f}% 트레일+{ST_TRAIL_ACT*100:.1f}%
횡보:     비중{SW_SIZE_PCT*100:.0f}% 익절{SW_TP_PCT*100:.1f}% 손절{SW_SL_PCT*100:.1f}%
월한도:   -{MONTHLY_MAX_LOSS*100:.0f}%
""")

    init_session()
    run_loop()

"""v7 config: env vars + immutable strategy/risk constants.

Environment variables override defaults; safety guards (daily/weekly/monthly
loss limits) are *not* environment-tunable and are enforced in safety.py.
"""
from __future__ import annotations
import os

# ─── Credentials ───────────────────────────────────────────────
API_KEY    = os.environ.get("BYBIT_API_KEY", "")
API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
TESTNET    = os.environ.get("TESTNET", "false").lower() == "true"

# ─── Symbols / loop ───────────────────────────────────────────
# v12: 다중 심볼 지원. SYMBOLS 환경변수 콤마 구분.
# 미지정시 SYMBOL (단일) 환경변수 → 그것도 없으면 BTCUSDT 단일.
def _parse_symbols() -> list[str]:
    env_multi = os.environ.get("SYMBOLS", "").strip()
    if env_multi:
        return [s.strip().upper() for s in env_multi.split(",") if s.strip()]
    single = os.environ.get("SYMBOL", "BTCUSDT").strip().upper()
    return [single]

SYMBOLS    = _parse_symbols()
SYMBOL     = SYMBOLS[0]  # 레거시 호환 (단일 심볼 코드 경로)
LOOP_SEC   = int(os.environ.get("LOOP_SEC", "30"))
POSITION_MODE = os.environ.get("POSITION_MODE", "one_way")

# ─── Capital / sizing (v13: score-based, global cap, no /N split) ──
# v13 변경: 1/N 분할 제거. 각 심볼이 tier의 full 마진을 사용하되,
# 전체 활성 포지션 합산 마진이 MAX_TOTAL_MARGIN 이하로 유지.
# score_factor = (score/100)^SCORE_EXP 로 강한 신호일수록 큰 사이즈.
MARGIN_PCT_MICRO = 0.30   # 3x  → notional 90%   equity
MARGIN_PCT_PROBE = 0.40   # 5x  → notional 200%
MARGIN_PCT_BASE  = 0.50   # 10x → notional 500%
MARGIN_PCT_MID   = 0.65   # 15x → notional 975%
MARGIN_PCT_HIGH  = 0.80   # 20x → notional 1600%
MARGIN_PCT_MR    = 0.50   # MR 5x → notional 250%
# Legacy single-margin (display/fallback)
MARGIN_PCT       = float(os.environ.get("MARGIN_PCT", "0.50"))
# 봇이 실제로 사용하는 자본 비율 (나머지는 buffer)
CAPITAL_FRACTION = float(os.environ.get("CAPITAL_FRACTION", "1.00"))

# v13: 전체 활성 포지션 마진 합계 한도. 1.0 = 잔고 100%.
# v13.1: 기본 0.90 (10% 버퍼) — Bybit 가 수수료/maintenance margin 위해
#         실제 가용 잔고를 entry 마진보다 더 빡빡하게 잡음. 100% 까지 채우면
#         110007 'ab not enough' 에러 자주 남.
# 0.85 = 보수 / 0.90 = 권장 / 1.00 = 빡빡 / 1.50 = 공격적 (위험)
MAX_TOTAL_MARGIN = float(os.environ.get("MAX_TOTAL_MARGIN", "0.90"))

# v13: 점수 → 마진 스케일링 곡선 (margin = tier × (score/100)^SCORE_EXP)
# 1.0 = 선형 (직관적), 1.5 = 가파름, 2.0 = 매우 가파름
SCORE_EXP = float(os.environ.get("SCORE_EXP", "1.0"))

# ─── Strategy D v9 (5-tier aggressive + per-tier exit + per-tier margin) ──
# v5.0: D 단독 32% 승률 (횡보장 데이터)
# v6.27: STRATEGY_MODE=BOTH 기본 — 추세장(ADX>32) D 작동, 횡보장 MR 작동
#        MR 코드에 ADX>32 hard gate 있어서 자동 분리됨
STRATEGY_MODE     = os.environ.get("STRATEGY_MODE", "BOTH").upper()  # "D" / "MR" / "BOTH"
ENTRY_MIN_SCORE   = 55.0
# v6.28: D 점수 ≥ 70 (base/mid/high) 패자 분석 → 반대매매 (inverse) 시도
# 데이터: 50건 -$94 손실 + 점수 역상관 (-5.3) + server_stop 56%
# 70 점 이상은 추세 끝물 잡는 패턴 가설로 long ↔ short 반전
# 환경변수로 임계치 조정 가능 (200 = 비활성)
D_INVERSE_THRESHOLD = float(os.environ.get("D_INVERSE_THRESHOLD", "70"))
SCORE_TIER_MICRO  = 60.0   # 55..59 → 3x
SCORE_TIER_PROBE  = 70.0   # 60..69 → 5x
SCORE_TIER_BASE   = 80.0   # 70..79 → 10x
SCORE_TIER_MID    = 90.0   # 80..89 → 15x; >=90 → 20x
LEV_TIER_MICRO    = 3.0
LEV_TIER_PROBE    = 5.0
LEV_TIER_BASE     = 10.0
LEV_TIER_MID      = 15.0
LEV_TIER_HIGH     = 20.0

# Per-tier exit policy v9 — option A (more extreme on both ends):
#   low tiers cash out faster (smaller TP)
#   high tiers trail wider (let trends run)
TP_MARGIN_MICRO   = 0.02   # micro: +2% margin → close (was +3%)
TP_MARGIN_PROBE   = 0.03   # probe: +3% margin → close (was +5%)
TP_MARGIN_BASE    = 0.06   # base:  +6% margin → close (was +10%)
TP1_MARGIN_MID    = 0.10   # mid:   TP1 +10% partial 50% → BE+trail rest
TP_MARGIN_HIGH    = None   # high:  no fixed TP — BE+trail only

# v6.32: 2단계 분할 익절 + Dynamic trail (mid/high tier)
# 사용자 케이스: BNB +$100 정점 → 풀백 → 트레일 발동 못함 → 수익 토함
# 해결: 일찍 일부 잠금 + 수익 클수록 trail 조여짐
# Mid tier 2단계 (current TP1 +10% 50% → 30/30/40 분할)
TP1_RATIO_MID     = 0.30   # mid TP1 (+10% margin) 30% 청산
TP2_MARGIN_MID    = 0.20   # mid TP2 (+20% margin)
TP2_RATIO_MID     = 0.30   # mid TP2 30% 청산 (누적 60%)
# High tier 2단계 분할 익절 신규
TP1_MARGIN_HIGH   = 0.05   # high TP1 +5% margin → 30% 청산
TP1_RATIO_HIGH    = 0.30
TP2_MARGIN_HIGH   = 0.15   # high TP2 +15% margin → 30% 청산 (누적 60%)
TP2_RATIO_HIGH    = 0.30
# Dynamic trail — 수익 클수록 trail 조여짐 (high tier 만)
DYNAMIC_TRAIL_ENABLED   = True
TRAIL_PEAK_TIGHT_PCT    = 0.10   # peak margin ≥ +10% 시 1.5×ATR 로 조임
TRAIL_PEAK_VTIGHT_PCT   = 0.20   # peak margin ≥ +20% 시 1.0×ATR 로 더 조임
TRAIL_ATR_HIGH_TIGHT    = 1.5
TRAIL_ATR_HIGH_VTIGHT   = 1.0

# Per-tier ATR trail multiplier (v10.2: widened — let trends run further;
# previously mid=2.5 / high=3.0 cashed out on normal pullbacks)
TRAIL_ATR_DEFAULT = 1.5
TRAIL_ATR_MID     = 2.0   # v6.32: 3.0 → 2.0 (mid 도 좀 더 빠르게)
TRAIL_ATR_HIGH    = 4.0

# ─── Stop / trail ──────────────────────────────────────────────
ATR_STOP_MULT  = 1.5
ATR_TRAIL_MULT = 1.5
COOLDOWN_BARS_LOSS = 6      # 6 × 15m = 90 min after a stop

# ─── Hard safety guards (immutable; set in safety.py) ──────────
# Daily loss -3% → 24h halt
# Weekly loss -7% → 7d halt
# Monthly loss -12% → 30d halt
# These are NOT exposed via env to prevent mid-blowup tampering.

# ─── Persistence ───────────────────────────────────────────────
STATE_PATH      = os.environ.get("STATE_PATH",      "/data/state_v7.json")
TRADE_LOG_PATH  = os.environ.get("TRADE_LOG_PATH",  "/data/trades_v7.jsonl")
SAFETY_PATH     = os.environ.get("SAFETY_PATH",     "/data/safety_v7.json")

# ─── AI layer (Gemini free tier) ───────────────────────────────
# Disabled unless GEMINI_API_KEY is set AND AI_ENABLED=true.
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
AI_ENABLED      = os.environ.get("AI_ENABLED", "false").lower() == "true"
AI_MODEL        = os.environ.get("AI_MODEL", "gemini-2.0-flash")
# Regime detection cadence (seconds). Free tier easily handles 1h.
AI_REGIME_INTERVAL_SEC = int(os.environ.get("AI_REGIME_INTERVAL_SEC", "3600"))

# ─── Symbol decimals (price + qty) ─────────────────────────────
PRICE_DECIMALS = {
    "BTCUSDT": 1, "ETHUSDT": 2, "SOLUSDT": 3,
    "BNBUSDT": 2, "XRPUSDT": 4, "LINKUSDT": 3,
}
QTY_DECIMALS = {
    "BTCUSDT": 3, "ETHUSDT": 2, "SOLUSDT": 1,
    "BNBUSDT": 2, "XRPUSDT": 0, "LINKUSDT": 1,
}

# Disaster SL placed server-side at -2% (catches even if bot crashes)
DISASTER_SL_PCT = 0.02

# v6.33A: 시간대 자동 차단 (KST 시간) — /diagnose 데이터 기반
# 06~12 KST 시간대가 -$87 (최대 손실 구간) → 해당 시간 진입 차단
# CSV 형식 (예: "6,7,8,9,10,11"). 빈 문자열이면 차단 없음.
BLOCKED_HOURS_KST = os.environ.get("BLOCKED_HOURS_KST", "6,7,8,9,10,11")

def _parse_blocked_hours() -> set:
    s = BLOCKED_HOURS_KST.strip()
    if not s:
        return set()
    try:
        return {int(h) for h in s.split(",") if h.strip()}
    except Exception:
        return set()

BLOCKED_HOURS_KST_SET = _parse_blocked_hours()

# v6.33C: 자동 회복 휴식 — 일일 손실 도달시 다음날까지 진입 차단
DAILY_LOSS_REST_PCT = float(os.environ.get("DAILY_LOSS_REST_PCT", "0.03"))   # -3%

# v6.33B: AI Final Gate — 진입 직전 Gemini 한 번 더 호출
AI_FINAL_GATE_ENABLED = os.environ.get("AI_FINAL_GATE_ENABLED", "true").lower() == "true"
AI_FINAL_GATE_MIN_TIER = os.environ.get("AI_FINAL_GATE_MIN_TIER", "base")  # base 이상만 (작은 진입은 통과)

# v6.34 B5: 상관관계 디텍터 — BTC 큰 움직임시 알트도 따라감 가정
# BTC 가 4H 기준 같은 방향으로 큰 움직임 → 알트 같은 방향 진입 부스트
# 반대 방향 알트 진입은 차단 (BTC 추세 거스름)
CORRELATION_DETECTOR_ENABLED = os.environ.get("CORR_ENABLED", "true").lower() == "true"

# v6.34 B6: 같은 방향 N종 이상 동시 진입 차단 (집중 위험 ↓)
# 예: BTC, ETH, SOL 셋 다 숏인데 XRP, BNB 도 숏 진입하려 하면 차단
MAX_SAME_DIRECTION_POSITIONS = int(os.environ.get("MAX_SAME_DIRECTION_POS", "3"))

# v6.34 A4: 부진 심볼 자동 휴식 — 지난 N일 -X% 손실 누적시 24h 진입 차단
SYMBOL_REST_DAYS = int(os.environ.get("SYMBOL_REST_DAYS", "7"))           # 평가 기간
SYMBOL_REST_LOSS_THRESHOLD = float(os.environ.get("SYMBOL_REST_LOSS_THRESHOLD", "10.0"))  # -$10 누적
SYMBOL_REST_HOURS = int(os.environ.get("SYMBOL_REST_HOURS", "24"))        # 휴식 시간

# v6.35 A1b: AI Hold Check — 보유중 포지션 조기 청산 평가
AI_HOLD_CHECK_ENABLED = os.environ.get("AI_HOLD_CHECK_ENABLED", "true").lower() == "true"
AI_HOLD_CHECK_MIN_PROFIT = float(os.environ.get("AI_HOLD_CHECK_MIN_PROFIT", "0.05"))  # peak +5% margin 이상에서만

# v6.35 A3: 레짐 deep analysis — 룰 + 뉴스 + AI 통합
AI_REGIME_DEEP_ENABLED = os.environ.get("AI_REGIME_DEEP_ENABLED", "true").lower() == "true"
AI_REGIME_DEEP_INTERVAL_SEC = int(os.environ.get("AI_REGIME_DEEP_INTERVAL_SEC", "14400"))  # 4시간 간격

# v6.43: Claude Agent — 시간별 자율 분석 + PR 제안
# 필수 env: ANTHROPIC_API_KEY (https://console.anthropic.com)
# 선택 env: GH_PAT (PR 생성용 GitHub Personal Access Token)
CLAUDE_AGENT_ENABLED = os.environ.get("CLAUDE_AGENT_ENABLED", "true").lower() == "true"
CLAUDE_AGENT_INTERVAL_SEC = int(os.environ.get("CLAUDE_AGENT_INTERVAL_SEC", "3600"))  # 1시간
CLAUDE_AGENT_MODEL = os.environ.get("CLAUDE_AGENT_MODEL", "claude-sonnet-4-6")

# Refresh OHLCV cache every N seconds within a loop iteration (avoid spam)
CACHE_15M_SEC = 30
CACHE_1H_SEC  = 600
CACHE_4H_SEC  = 1800

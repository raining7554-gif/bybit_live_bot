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
# v6.49 A: SOL universe 제외 (30일 -$138 단독 손실원)
# env SYMBOL_BLACKLIST 로 차단 종목 콤마 구분 지정
_blacklist = set(
    s.strip().upper()
    for s in os.environ.get("SYMBOL_BLACKLIST", "SOLUSDT").split(",")
    if s.strip()
)
SYMBOLS    = [s for s in SYMBOLS if s not in _blacklist]
SYMBOL     = SYMBOLS[0] if SYMBOLS else "BTCUSDT"  # 레거시 호환
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
# v6.63: 기본값 65 → 200 (실질 비활성). 트렌딩 시장에서 D_INV 가 손실 폭주 원인.
# 트렌딩 레짐에선 절대 반전 금지, 레인징 레짐에서만 선별 사용 (regime gate 도입).
D_INVERSE_THRESHOLD = float(os.environ.get("D_INVERSE_THRESHOLD", "200"))
# v6.63: D_INV 는 ranging 레짐 + 매우 높은 점수 (90+) 에서만 발동 허용
# regime 분류가 'ranging' 이고 점수 >= D_INVERSE_RANGING_MIN 일 때만 인버스 적용
D_INVERSE_REGIME_GATED = os.environ.get("D_INVERSE_REGIME_GATED", "true").lower() == "true"
D_INVERSE_RANGING_MIN = float(os.environ.get("D_INVERSE_RANGING_MIN", "85"))

# v6.63: 레짐 기반 전략 선택 (김민겸 다전략 풀 접근)
# trending → D 만 (no inverse, trend ride)
# ranging  → MR 만 (no D, mean revert)
# mixed    → 둘 다 micro 사이즈로
REGIME_GATED_STRATEGY = os.environ.get("REGIME_GATED", "true").lower() == "true"
# 레짐 확신도가 이 임계 이하면 게이트 무시 (분류 불확실 = 보수적 패스스루)
REGIME_GATE_MIN_CONF = float(os.environ.get("REGIME_GATE_MIN_CONF", "0.55"))

# v6.54: mid/high tier (점수 80+) 사이즈 캡
# 데이터 (30일): mid 10건 -$98 / high 6건 -$74 = 16건 -$172
# 점수-승률 무상관 (-0.2) → 큰 사이즈 진입이 손실 증폭
# True 면 80+ 점수도 base tier (10x/50%) 사이즈 적용
TIER_CAP_ENABLED = os.environ.get("TIER_CAP_ENABLED", "true").lower() == "true"
SCORE_TIER_MICRO  = 60.0   # 55..59 → 3x
SCORE_TIER_PROBE  = 70.0   # 60..69 → 5x
SCORE_TIER_BASE   = 80.0   # 70..79 → 10x
SCORE_TIER_MID    = 90.0   # 80..89 → 15x; >=90 → 20x
LEV_TIER_MICRO    = 3.0
LEV_TIER_PROBE    = 5.0
LEV_TIER_BASE     = 10.0
LEV_TIER_MID      = 15.0
LEV_TIER_HIGH     = 20.0

# v6.63: 최대 레버리지 하드 캡 (env 로 조정)
# 학술 권고 (Quarter-Kelly): BTC 60% 연변동 가정 시 5x 부근이 합리적.
# 사용자 기존 운영 호환 위해 default 20 유지. 보수 운영시 5~10 권장.
MAX_LEVERAGE_CAP  = float(os.environ.get("MAX_LEVERAGE_CAP", "20.0"))

# v6.64: 최소 R:R 필터 (수수료 차감 후)
# 승률 좋은데 마이너스 = R:R 비대칭. 수수료 차감 net_TP/net_SL 비율이
# MIN_RR_FILTER 미만이면 진입 차단. 1.3 = 보수적, 1.5 = 적극적 필터.
# 0.0 = 비활성 (기존 동작 유지).
MIN_RR_FILTER     = float(os.environ.get("MIN_RR_FILTER", "1.2"))
# Bybit V5 taker 수수료 — R:R 계산용. perp 무기한 기준.
TAKER_FEE_BPS     = float(os.environ.get("TAKER_FEE_BPS", "5.5"))   # 0.055%

# Per-tier exit policy v9 — option A (more extreme on both ends):
#   low tiers cash out faster (smaller TP)
#   high tiers trail wider (let trends run)
# v6.64: 승률 좋은데 마이너스 = R:R 비대칭 + 수수료 문제 해결
# - 10x 레버리지에서 왕복 taker 수수료만 2.2% 마진
# - 기존 TP base +6% 마진 → 수수료 차감 후 +3.8% / 손절 -8.2%
# - 손익분기 승률 68% 요구 → 65% 승률에도 마이너스
# 해결: TP 거리 확대 (R:R 1.5:1 이상 확보)
TP_MARGIN_MICRO   = 0.04   # v6.64: 2% → 4% (3x 에서도 수수료 0.66% 차감 후 net +3.3%)
TP_MARGIN_PROBE   = 0.06   # v6.64: 3% → 6% (5x 수수료 1.1% 차감 후 net +4.9%)
TP_MARGIN_BASE    = 0.10   # v6.64: 6% → 10% (10x 수수료 2.2% 차감 후 net +7.8%)
TP1_MARGIN_MID    = 0.12   # v6.64: 10% → 12% (mid TP1 더 멀리)
TP_MARGIN_HIGH    = None   # high:  no fixed TP — BE+trail only

# v6.32: 2단계 분할 익절 + Dynamic trail (mid/high tier)
# 사용자 케이스: BNB +$100 정점 → 풀백 → 트레일 발동 못함 → 수익 토함
# 해결: 일찍 일부 잠금 + 수익 클수록 trail 조여짐
# v6.64: 승률 좋은데 마이너스 → TP1 청산 비율 30% → 50% 확대
# (작은 wins 가 트레일 BE 까지 되돌아가서 +1.5% 만 챙기던 문제)
TP1_RATIO_MID     = 0.50   # v6.64: 30% → 50% (mid TP1 +12% 에서 절반 청산)
TP2_MARGIN_MID    = 0.22   # v6.64: 20% → 22% (TP1 멀어진 만큼)
TP2_RATIO_MID     = 0.30   # mid TP2 30% 청산 (누적 80%)
# High tier 2단계 분할 익절
TP1_MARGIN_HIGH   = 0.08   # v6.64: 5% → 8% (수수료 차감 후 +5.8% 확보)
TP1_RATIO_HIGH    = 0.50   # v6.64: 30% → 50%
TP2_MARGIN_HIGH   = 0.18   # v6.64: 15% → 18%
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

# v6.33A → v6.47: 시간대 자동 차단 default OFF (사용자 요청 "정지 빼줘")
# env 로 다시 활성 원하면: BLOCKED_HOURS_KST="6,7,8,9,10,11"
BLOCKED_HOURS_KST = os.environ.get("BLOCKED_HOURS_KST", "")

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
# v6.63: Gemini quota 절약 — (symbol, side) 별 1800s 쓰로틀, mid 이상만 호출
AI_FINAL_GATE_ENABLED = os.environ.get("AI_FINAL_GATE_ENABLED", "true").lower() == "true"
AI_FINAL_GATE_MIN_TIER = os.environ.get("AI_FINAL_GATE_MIN_TIER", "mid")  # v6.63: base → mid
AI_FINAL_GATE_THROTTLE_SEC = int(os.environ.get("AI_FINAL_GATE_THROTTLE_SEC", "1800"))

# v6.63: pattern_check 쓰로틀 (intelligence/agent.py 의 Gemini 콜)
# 같은 (symbol, direction) 신호가 짧은 시간 안에 반복되면 한 번만 호출
AI_PATTERN_CHECK_ENABLED = os.environ.get("AI_PATTERN_CHECK_ENABLED", "true").lower() == "true"
AI_PATTERN_THROTTLE_SEC = int(os.environ.get("AI_PATTERN_THROTTLE_SEC", "3600"))
# pattern_check 도 mid 이상만 (작은 사이즈 진입엔 호출 X)
AI_PATTERN_MIN_TIER = os.environ.get("AI_PATTERN_MIN_TIER", "mid")

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
# v6.65: default false 로 전환 (비용 통제). 수동 /agent 명령은 그대로 동작.
# 자동 사이클 다시 켜려면 Railway env CLAUDE_AGENT_ENABLED=true 명시.
CLAUDE_AGENT_ENABLED = os.environ.get("CLAUDE_AGENT_ENABLED", "false").lower() == "true"
# v6.55: 시간별 → 6시간 간격 (비용 절감, 사용자 요청)
# 24 사이클/일 × multi-iteration = 너무 빠른 소진 → 4 사이클/일로
CLAUDE_AGENT_INTERVAL_SEC = int(os.environ.get("CLAUDE_AGENT_INTERVAL_SEC", "21600"))  # 6시간
CLAUDE_AGENT_MODEL = os.environ.get("CLAUDE_AGENT_MODEL", "claude-sonnet-4-6")

# ─── Swing 모드 (v6.63: 4H 고확신 추세 장기 보유) ──────────────
# trending 레짐 + 강한 4H ADX + 다중 심볼 컨플루언스 일치 시 활성
# 15m 노이즈 무시, 1H/4H 시그널만 청산 트리거. 트레일 더 넓게.
SWING_MODE_ENABLED = os.environ.get("SWING_MODE_ENABLED", "true").lower() == "true"
SWING_ADX_4H_MIN = float(os.environ.get("SWING_ADX_4H_MIN", "30.0"))
SWING_CROSS_AGREE_MIN = float(os.environ.get("SWING_CROSS_AGREE_MIN", "0.7"))
SWING_TRAIL_ATR_MULT = float(os.environ.get("SWING_TRAIL_ATR_MULT", "5.0"))
# swing 포지션은 mid/high 사이즈 캡 무시 — 추세 큰 거 잡는 게 목적
SWING_TIER_CAP_BYPASS = os.environ.get("SWING_TIER_CAP_BYPASS", "true").lower() == "true"

# Refresh OHLCV cache every N seconds within a loop iteration (avoid spam)
CACHE_15M_SEC = 30
CACHE_1H_SEC  = 600
CACHE_4H_SEC  = 1800

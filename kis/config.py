"""설정 v3.0 — 섹터 스윙 전략 (국장 50만 + 나스닥 50만 시드 가정)"""
import os

# ── KIS API ───────────────────────────────────────────
APP_KEY    = os.environ.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
ACCOUNT_NO = os.environ.get("KIS_ACCOUNT_NO", "")
IS_PAPER   = os.environ.get("KIS_PAPER", "false").lower() == "true"

# ── 텔레그램 ──────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────────────────
# 국내(한국장) 설정
# ─────────────────────────────────────────────────────────
# 시드 가정 (실계좌 잔고로 동적 계산하지만 유니버스 필터링 기준용)
DOM_ASSUMED_SEED = 500_000          # 50만원

# 운영 시간 — 스윙이므로 신규 진입만 제한, 청산은 언제든
DOM_SCAN_START  = "09:30"           # 오전장 안정화 후
DOM_SCAN_END    = "14:00"           # 종가 직전 피함
DOM_EOD_CHECK   = "15:15"           # 일봉 청산 조건 체크
DOM_CLOSING_MSG = "15:35"           # 결산 알림

# 포지션
DOM_MAX_POSITIONS = 2               # 시드 작으니 2종목 분산이 현실적
DOM_POSITION_PCT  = 0.45            # 시드의 45%씩 (2종목 = 90%, 버퍼 10%)
DOM_UNIVERSE_MAX_PRICE = 150_000    # 유니버스 가격 상한(1주라도 살 수 있게)
DOM_UNIVERSE_MIN_PRICE = 2_000      # 저가 작전주 회피

# 청산 조건 (스윙)
DOM_STOP_LOSS      = 0.03           # -3% 하드 손절 (swing 모드용)
DOM_TRAIL_ACTIVATE = 0.03           # +3% 도달 시 트레일링 활성
DOM_TRAIL_DROP     = 0.05           # 고점 대비 -5%
DOM_MAX_HOLD_DAYS  = 10             # 최대 10영업일

# v4.0: Clenow 모드 장중 비상 손절 — 블랙스완 방어
# Clenow 철학(MA50 이탈로만 청산) 유지하되, 극단적 폭락만 cut.
# 본인 시드 기준 -7% × 12.5% 배분 = -0.875% 잔고 영향. 작은 페널티로 대형 사고 방지.
DOM_CLENOW_EMERGENCY_SL = 0.07      # 장중 -7% 도달시 즉시 청산

# ─────────────────────────────────────────────────────────
# 해외(나스닥) 설정
# ─────────────────────────────────────────────────────────
OS_ASSUMED_SEED_USD = 350           # 약 50만원

# 운영 시간 (KST 기준, 서머타임 고려 않고 넉넉히)
# v3.3: 진입창 풀 확장 — 기본 22:30 (개장) ~ 05:30 (종료 직전).
# is_os_scan_time() 가 자정 넘어가는 윈도우(START > END) 자동 감지.
OS_SCAN_TIME_START  = os.environ.get("OS_SCAN_TIME_START", "22:30")
OS_SCAN_TIME_END    = os.environ.get("OS_SCAN_TIME_END", "05:30")
OS_EOD_CHECK        = os.environ.get("OS_EOD_CHECK", "05:45")  # 미장 종료 직전 일봉 청산 체크

# 포지션
OS_MAX_POSITIONS  = 2               # $350 시드면 2종목이 현실적
OS_POSITION_USD   = 150             # 1종목당 $150 목표
OS_QQQ_BASE_USD   = 50              # QQQ 방어용 베이스 (상승장에서만)

# 청산 조건
OS_STOP_LOSS      = 0.05            # -5% 하드 손절 (장중 실시간 봇 감시)
OS_TRAIL_DROP     = 0.10            # 고점 대비 -10% (기본값, ATR 적응시 무시)
OS_PANIC_TRIGGER  = 0.02            # QQQ -2% 이상 급락 시 방어 가동

# v4.0: 변동성 적응형 트레일 (ATR 기반)
# 종목별 ATR 따라 trail 폭 자동 조정 (저변동 = 빠르게 잡기, 고변동 = 풀백 견딤)
OS_TRAIL_ATR_MULT = 1.5             # ATR × 1.5 만큼 trail (대략 7~13% 범위)
OS_TRAIL_MIN      = 0.07            # 최소 7%
OS_TRAIL_MAX      = 0.13            # 최대 13%
# 나스닥은 최대 보유일 제한 없음 — 추세 유효하면 계속 보유

# ─────────────────────────────────────────────────────────
# 전략 모드 선택 (v3.2 추가)
# ─────────────────────────────────────────────────────────
# 국내: "swing" (기존 섹터 스윙) | "clenow" (120일 모멘텀, 튜닝 완료)
DOM_STRATEGY_MODE = os.environ.get("DOM_STRATEGY_MODE", "swing")
# 해외: "swing" (기존) | "leveraged" (SOXL/TQQQ 체제 스위치)
OS_STRATEGY_MODE = os.environ.get("OS_STRATEGY_MODE", "swing")

# ── Clenow 국내 파라미터 ─────────────────────────────
CLENOW_WINDOW         = 120          # 회귀 일수
CLENOW_TOP_PCT        = 0.10         # 상위 10%만 진입
CLENOW_EXIT_MA        = 50           # MA50 이탈 시 청산
CLENOW_MAX_POSITIONS  = 8            # 최대 8종목 분산

# ── 소액 시드 모드 (튜닝 가능) ──────────────────────
# 시드 작을 때: 8포지션 × 12.5% 배분이 의미 없음 (1주도 못 사는 종목 다수)
# 시드 규모별 권장:
#   ₩100~300k:  POSITIONS=1, MAX_PRICE=100,000
#   ₩300k~1M:   POSITIONS=2, MAX_PRICE=200,000  ← 현재 ₩500k 시드 권장
#   ₩1M+:       SMALL_SEED_MODE=false (8포지션 풀 분산)
DOM_SMALL_SEED_MODE      = os.environ.get("DOM_SMALL_SEED_MODE", "false").lower() == "true"
DOM_SMALL_SEED_POSITIONS = int(os.environ.get("DOM_SMALL_SEED_POSITIONS", "1"))
DOM_SMALL_SEED_MAX_PRICE = int(os.environ.get("DOM_SMALL_SEED_MAX_PRICE", "100000"))
# 비중: (총자본 95%) / 포지션수
DOM_SMALL_SEED_POSITION_PCT = 0.95 / max(DOM_SMALL_SEED_POSITIONS, 1)

# US 소액: 콤마 구분 티커 (예: "SOXL" 단일, 또는 "SOXL,TQQQ" 2-way)
# 벤치는 자동: SOXL/TECL → QQQ, TQQQ/UPRO/FAS → SPY
OS_SMALL_SEED_MODE       = os.environ.get("OS_SMALL_SEED_MODE", "false").lower() == "true"
OS_SMALL_SEED_TICKERS    = os.environ.get("OS_SMALL_SEED_TICKERS", "SOXL")  # CSV
# 레거시 호환 (단일 티커)
OS_SMALL_SEED_TICKER     = os.environ.get("OS_SMALL_SEED_TICKER", "SOXL")
OS_SMALL_SEED_BENCHMARK  = os.environ.get("OS_SMALL_SEED_BENCHMARK", "QQQ")

# 자동 벤치 매핑 (티커 → SPY 또는 QQQ)
_BENCH_MAP = {
    "SOXL": "QQQ", "TECL": "QQQ", "QQQ": "QQQ",
    "TQQQ": "SPY", "UPRO": "SPY", "FAS": "SPY",
    "TNA": "SPY", "UDOW": "SPY", "MIDU": "SPY", "CURE": "SPY",
}

def _parse_small_seed_allocations() -> list[dict]:
    """OS_SMALL_SEED_TICKERS 파싱하여 동가중 배분 리스트 반환"""
    tickers = [t.strip().upper() for t in OS_SMALL_SEED_TICKERS.split(",") if t.strip()]
    n = len(tickers)
    if n == 0:
        tickers = [OS_SMALL_SEED_TICKER]
        n = 1
    weight = 1.0 / n
    return [
        {"ticker": t, "benchmark": _BENCH_MAP.get(t, "SPY"), "weight": weight}
        for t in tickers
    ]

OS_SMALL_SEED_ALLOCATIONS = _parse_small_seed_allocations()

# ── 해외 레버리지 체제 스위치 파라미터 ──────────────
# 백테스트 결과 (2015-2026, $700 시드):
#   - 단일 SOXL/Cash:  CAGR +41% / MDD -71%  → $34,432
#   - 4-way 분산:      CAGR +38% / MDD -44%  → $25,029  ⭐ 채택
#
# 4-way: SOXL(3x 반도체) + TQQQ(3x 나스닥) + TECL(3x 기술) + FAS(3x 금융)
# 각 25% 배분, 벤치 독립 체제 스위치, BEAR 시 해당 슬리브만 현금 도피
OS_LEVERAGED_SIGNAL_MA = 200
OS_LEVERAGED_AUX_MA    = 50

# 슬리브 구성 — [{"ticker": ETF, "benchmark": 벤치, "weight": 비중}, ...]
# 비중 합 = 1.0
OS_LEVERAGED_ALLOCATIONS = [
    {"ticker": "SOXL", "benchmark": "QQQ", "weight": 0.25},
    {"ticker": "TQQQ", "benchmark": "SPY", "weight": 0.25},
    {"ticker": "TECL", "benchmark": "QQQ", "weight": 0.25},
    {"ticker": "FAS",  "benchmark": "SPY", "weight": 0.25},
]

# 레거시 호환 (단일 ETF 모드 쓰려면)
OS_LEVERAGED_BENCHMARK = "SPY"
OS_LEVERAGED_BULL      = "TQQQ"
OS_LEVERAGED_BEAR      = None

# ─────────────────────────────────────────────────────────
# 리스크 관리 (v3.1 추가)
# ─────────────────────────────────────────────────────────
# 시장가 주문 시 현재가 대비 허용 편차 — 이보다 크면 매수 취소
# v4.0: 2% → 1% 로 강화 (실제 운영시 +2.15% 슬리피지로 미체결 발생)
SLIPPAGE_GUARD_PCT = 0.01

# v4.0 차후 추가 예정 (v4.1): 진짜 지정가 주문 + 미체결 모니터링
# 현재는 시장가 + 강화된 슬리피지 가드로 충분

# v4.0 Phase 2A: 변동성 기반 리스크 패리티 사이징
# 모든 포지션이 비슷한 일일 변동 리스크 갖도록 자동 조정.
# 저변동 종목 = 큰 사이즈, 고변동 종목 = 작은 사이즈 → 단일종목 폭락 충격 균등화.
RISK_PARITY_ENABLED = True       # False면 기존 균등 배분 유지
TARGET_DAILY_RISK_PCT = 0.005    # 종목당 일일 0.5% 변동 리스크 목표
MIN_POSITION_PCT = 0.05          # 최소 포지션 비율 (5% 이하면 진입 안함)

# v4.0 Phase 4: 유니버스 정제 — 시총 상위 N 종목만 사용
# 350 종목 전체 = 작전주/저유동성 종목 포함. 200 으로 줄이면 더 안전.
DOM_UNIVERSE_LIMIT = int(os.environ.get("DOM_UNIVERSE_LIMIT", "200"))

# v4.0 Phase 4: 세금 효율 — 미장 단기 매매 페널티 (양도세 절감 유도)
# 7일 미만 보유 + 작은 수익 (10% 미만) 시 매도 보류 (장기보유 유도).
# 단, 손절 (-5%) 또는 큰 수익 (+10%+) 은 제한 없음.
# False = 페널티 없음 (기본). True = 활성화.
US_HOLD_PERIOD_PENALTY = os.environ.get("US_HOLD_PERIOD_PENALTY", "false").lower() == "true"

# v4.0 Phase 2B: 단계별 부분 익절 — 추세 잡으면서 수익 잠금
# 각 레벨에 도달시 N% 청산. 나머지 25% 는 트레일/MA50 종료까지.
# (수익률, 청산비율) 리스트 — 낮은 수익률부터 정렬되어야 함.
PARTIAL_TP_LEVELS = [
    (0.15, 0.25),   # +15% → 25% 청산 (수익 일부 잠금)
    (0.30, 0.25),   # +30% → 추가 25% 청산
    (0.50, 0.25),   # +50% → 추가 25% 청산 (75% 누적 회수)
    # 나머지 25% 는 트레일/MA50 으로 끝까지
]

# 일일 누적 손실 한도 (총평가 대비) — 초과 시 당일 신규 진입 중단
DAILY_LOSS_CIRCUIT = 0.05      # -5% (국내 단독)
# v4.0: 통합 서킷 — 국내+해외 합계 잔고 기준 일일 손실 한도
TOTAL_DAILY_LOSS_CIRCUIT = 0.07  # -7% 합계 손실시 양쪽 다 정지

# ─────────────────────────────────────────────────────────
# 공통 루프 인터벌
# ─────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC     = 180         # 스캔 3분에 1회 (스윙이라 급할 것 없음)
MONITOR_INTERVAL_SEC  = 15          # 장중 모니터링 15초
SUMMARY_INTERVAL_SEC  = 3600        # 1시간에 1회 현황

# ─────────────────────────────────────────────────────────
# 레거시 호환 (다른 모듈이 import할 수도 있어 유지)
# ─────────────────────────────────────────────────────────
POSITION_SIZE_PCT = DOM_POSITION_PCT
MAX_POSITIONS     = DOM_MAX_POSITIONS
SCAN_START_TIME   = DOM_SCAN_START
SCAN_END_TIME     = DOM_SCAN_END
FORCE_CLOSE_TIME  = "99:99"         # 강제청산 안 함 (스윙)
TAKE_PROFIT_PCT   = DOM_TRAIL_ACTIVATE
STOP_LOSS_PCT     = DOM_STOP_LOSS

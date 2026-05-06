"""나스닥 스캐너 v4.1 — NASDAQ-100 + S&P 500 핵심 (universe 35 → 55)

유니버스 55종목. 가격 필터 자동 (OS_POSITION_USD 초과 종목 제외).
"""
from config import OS_POSITION_USD
from strategy_overseas import get_os_regime, check_os_entry, get_overseas_current

# v3.1 universe: NASDAQ-100 + 미국 반도체/AI/클라우드 핵심.
# 가격이 OS_POSITION_USD 초과면 런타임에 자동 스킵되므로 시드 규모 무관하게 등록.
OS_UNIVERSE = [
    # ── 메가캡 (FAANG + AI 대장) ──────────────────────────
    {"ticker": "NVDA",  "name": "엔비디아",        "exchange": "NAS"},
    {"ticker": "MSFT",  "name": "마이크로소프트",  "exchange": "NAS"},
    {"ticker": "GOOGL", "name": "알파벳",          "exchange": "NAS"},
    {"ticker": "META",  "name": "메타",            "exchange": "NAS"},
    {"ticker": "AAPL",  "name": "애플",            "exchange": "NAS"},
    {"ticker": "AMZN",  "name": "아마존",          "exchange": "NAS"},
    {"ticker": "TSLA",  "name": "테슬라",          "exchange": "NAS"},
    {"ticker": "NFLX",  "name": "넷플릭스",        "exchange": "NAS"},
    # ── 반도체 ────────────────────────────────────────────
    {"ticker": "AVGO",  "name": "브로드컴",        "exchange": "NAS"},
    {"ticker": "AMD",   "name": "AMD",             "exchange": "NAS"},
    {"ticker": "TSM",   "name": "TSMC",            "exchange": "NYS"},
    {"ticker": "INTC",  "name": "인텔",            "exchange": "NAS"},
    {"ticker": "QCOM",  "name": "퀄컴",            "exchange": "NAS"},
    {"ticker": "TXN",   "name": "텍사스인스트루먼츠", "exchange": "NAS"},
    {"ticker": "MU",    "name": "마이크론",        "exchange": "NAS"},
    {"ticker": "AMAT",  "name": "어플라이드머티리얼", "exchange": "NAS"},
    {"ticker": "LRCX",  "name": "램리서치",        "exchange": "NAS"},
    {"ticker": "KLAC",  "name": "KLA",             "exchange": "NAS"},
    {"ticker": "ASML",  "name": "ASML",            "exchange": "NAS"},
    {"ticker": "ARM",   "name": "ARM",             "exchange": "NAS"},
    {"ticker": "MRVL",  "name": "마벨",            "exchange": "NAS"},
    {"ticker": "ON",    "name": "온세미",          "exchange": "NAS"},
    # ── 클라우드 / SaaS / 보안 ─────────────────────────────
    {"ticker": "ORCL",  "name": "오라클",          "exchange": "NYS"},
    {"ticker": "CRM",   "name": "세일즈포스",      "exchange": "NYS"},
    {"ticker": "ADBE",  "name": "어도비",          "exchange": "NAS"},
    {"ticker": "NOW",   "name": "서비스나우",      "exchange": "NYS"},
    {"ticker": "INTU",  "name": "인튜이트",        "exchange": "NAS"},
    {"ticker": "PANW",  "name": "팔로알토",        "exchange": "NAS"},
    {"ticker": "CRWD",  "name": "크라우드스트라이크", "exchange": "NAS"},
    {"ticker": "ZS",    "name": "지스케일러",      "exchange": "NAS"},
    {"ticker": "DDOG",  "name": "데이터독",        "exchange": "NAS"},
    {"ticker": "ANET",  "name": "아리스타",        "exchange": "NYS"},
    {"ticker": "SNOW",  "name": "스노우플레이크",  "exchange": "NYS"},
    {"ticker": "FTNT",  "name": "포티넷",          "exchange": "NAS"},
    {"ticker": "MDB",   "name": "몽고DB",          "exchange": "NAS"},
    {"ticker": "NET",   "name": "클라우드플레어",  "exchange": "NYS"},
    {"ticker": "OKTA",  "name": "옥타",            "exchange": "NAS"},
    # ── 핀테크 / 신성장 / 기타 ─────────────────────────────
    {"ticker": "PLTR",  "name": "팔란티어",        "exchange": "NAS"},
    {"ticker": "COIN",  "name": "코인베이스",      "exchange": "NAS"},
    {"ticker": "SHOP",  "name": "쇼피파이",        "exchange": "NAS"},
    {"ticker": "UBER",  "name": "우버",            "exchange": "NYS"},
    {"ticker": "ABNB",  "name": "에어비앤비",      "exchange": "NAS"},
    {"ticker": "PYPL",  "name": "페이팔",          "exchange": "NAS"},
    {"ticker": "SQ",    "name": "블록(스퀘어)",    "exchange": "NYS"},
    {"ticker": "ROKU",  "name": "로쿠",            "exchange": "NAS"},
    # ── 헬스케어 (액션 큰 종목) ────────────────────────────
    {"ticker": "VRTX",  "name": "버텍스",          "exchange": "NAS"},
    {"ticker": "REGN",  "name": "리제너론",        "exchange": "NAS"},
    {"ticker": "ISRG",  "name": "인튜이티브서지컬", "exchange": "NAS"},
    {"ticker": "MRNA",  "name": "모더나",          "exchange": "NAS"},
    # ── 소비재 / 산업 (모멘텀 좋은 것만) ──────────────────
    {"ticker": "SBUX",  "name": "스타벅스",        "exchange": "NAS"},
    {"ticker": "NKE",   "name": "나이키",          "exchange": "NYS"},
    {"ticker": "DIS",   "name": "디즈니",          "exchange": "NYS"},
    # ── 인덱스 / 테마 ETF ────────────────────────────────
    {"ticker": "QQQ",   "name": "나스닥100 ETF",   "exchange": "NAS"},
    {"ticker": "SPY",   "name": "S&P500 ETF",      "exchange": "AMS"},
    {"ticker": "ARKK",  "name": "ARK이노베이션",   "exchange": "AMS"},
]


def scan_overseas_candidates(exclude_tickers: list = None) -> list:
    if exclude_tickers is None:
        exclude_tickers = []

    regime_info = get_os_regime()
    regime = regime_info["regime"]

    if regime == "BEAR":
        print(f"[OS_SCANNER] 국면 BEAR → 신규 진입 보류")
        return []

    candidates = []
    for stock in OS_UNIVERSE:
        ticker = stock["ticker"]
        if ticker in exclude_tickers:
            continue

        # 현재가 확인 — $150 예산으로 1주라도 살 수 있어야 함
        curr = get_overseas_current(ticker, stock["exchange"])
        if not curr or curr["price"] == 0:
            continue
        if curr["price"] > OS_POSITION_USD:
            print(f"[OS_SCANNER] ⏭️  {stock['name']}({ticker}) ${curr['price']:.2f} → 예산 초과")
            continue

        ok, reason, metrics = check_os_entry(ticker, stock["exchange"], stock["name"])
        if not ok:
            print(f"[OS_SCANNER] ❌ {stock['name']}({ticker}) {reason}")
            continue

        candidates.append({
            "ticker": ticker,
            "name": stock["name"],
            "exchange": stock["exchange"],
            "price": curr["price"],
            "change_rate": curr["change_rate"],
            "volume": curr["volume"],
            "atr_pct": metrics.get("atr_pct"),  # v4.0
            "market": "overseas",
            "regime": regime,
            "reason": reason,
            "metrics": metrics,
        })
        print(f"[OS_SCANNER] ✅ {stock['name']}({ticker}) ${curr['price']:.2f} {reason}")

    # RSI 낮은 것(덜 과열) 우선 → 가격 저렴한 순
    candidates.sort(key=lambda x: (x["metrics"].get("rsi", 70), x["price"]))
    print(f"[OS_SCANNER] 완료 - {len(candidates)}개 후보 [{regime}]")
    return candidates


# 레거시 호환
def detect_overseas_regime() -> str:
    return get_os_regime().get("regime", "BULL")

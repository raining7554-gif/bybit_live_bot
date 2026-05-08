"""나스닥 스캐너 v6.12 — NASDAQ-100 + S&P 500 핵심 + 미드캡 (universe 55 → 120)

유니버스 ~120종. 가격 필터 자동 (OS_POSITION_USD 초과 종목 제외, 단 fractional 모드시 OFF).
"""
from config import OS_POSITION_USD
from strategy_overseas import get_os_regime, check_os_entry, get_overseas_current

# v6.12: 유니버스 대폭 확장. 사용자 요청 "종목 더 많이보자".
# 시드 작아도 자동 필터 (가격 > 예산이면 스킵), 모멘텀 후보 풀 다양화.
OS_UNIVERSE = [
    # ── 메가캡 (FAANG + AI 대장) ──────────────────────────
    {"ticker": "NVDA",  "name": "엔비디아",        "exchange": "NAS"},
    {"ticker": "MSFT",  "name": "마이크로소프트",  "exchange": "NAS"},
    {"ticker": "GOOGL", "name": "알파벳A",         "exchange": "NAS"},
    {"ticker": "GOOG",  "name": "알파벳C",         "exchange": "NAS"},
    {"ticker": "META",  "name": "메타",            "exchange": "NAS"},
    {"ticker": "AAPL",  "name": "애플",            "exchange": "NAS"},
    {"ticker": "AMZN",  "name": "아마존",          "exchange": "NAS"},
    {"ticker": "TSLA",  "name": "테슬라",          "exchange": "NAS"},
    {"ticker": "NFLX",  "name": "넷플릭스",        "exchange": "NAS"},
    {"ticker": "BRK.B", "name": "버크셔B",         "exchange": "NYS"},
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
    {"ticker": "ADI",   "name": "아날로그디바이스", "exchange": "NAS"},
    {"ticker": "MCHP",  "name": "마이크로칩",      "exchange": "NAS"},
    {"ticker": "NXPI",  "name": "NXP반도체",       "exchange": "NAS"},
    {"ticker": "SMCI",  "name": "수퍼마이크로",    "exchange": "NAS"},
    {"ticker": "STM",   "name": "ST마이크로",      "exchange": "NYS"},
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
    {"ticker": "WDAY",  "name": "워크데이",        "exchange": "NAS"},
    {"ticker": "TEAM",  "name": "아틀라시안",      "exchange": "NAS"},
    {"ticker": "TTD",   "name": "더트레이드데스크", "exchange": "NAS"},
    {"ticker": "GTLB",  "name": "깃랩",            "exchange": "NAS"},
    {"ticker": "S",     "name": "센티넬원",        "exchange": "NYS"},
    # ── 핀테크 / 신성장 ─────────────────────────────
    {"ticker": "PLTR",  "name": "팔란티어",        "exchange": "NAS"},
    {"ticker": "COIN",  "name": "코인베이스",      "exchange": "NAS"},
    {"ticker": "SHOP",  "name": "쇼피파이",        "exchange": "NAS"},
    {"ticker": "UBER",  "name": "우버",            "exchange": "NYS"},
    {"ticker": "ABNB",  "name": "에어비앤비",      "exchange": "NAS"},
    {"ticker": "PYPL",  "name": "페이팔",          "exchange": "NAS"},
    {"ticker": "SQ",    "name": "블록(스퀘어)",    "exchange": "NYS"},
    {"ticker": "ROKU",  "name": "로쿠",            "exchange": "NAS"},
    {"ticker": "HOOD",  "name": "로빈후드",        "exchange": "NAS"},
    {"ticker": "AFRM",  "name": "어펌",            "exchange": "NAS"},
    {"ticker": "SOFI",  "name": "소파이",          "exchange": "NAS"},
    {"ticker": "RBLX",  "name": "로블록스",        "exchange": "NYS"},
    # ── 금융 (대형 은행 / 카드) ─────────────────────
    {"ticker": "JPM",   "name": "JP모간",          "exchange": "NYS"},
    {"ticker": "BAC",   "name": "뱅크오브아메리카", "exchange": "NYS"},
    {"ticker": "WFC",   "name": "웰스파고",        "exchange": "NYS"},
    {"ticker": "GS",    "name": "골드만삭스",      "exchange": "NYS"},
    {"ticker": "MS",    "name": "모간스탠리",      "exchange": "NYS"},
    {"ticker": "V",     "name": "비자",            "exchange": "NYS"},
    {"ticker": "MA",    "name": "마스터카드",      "exchange": "NYS"},
    {"ticker": "AXP",   "name": "아메리칸익스프레스","exchange": "NYS"},
    {"ticker": "SCHW",  "name": "찰스슈왑",        "exchange": "NYS"},
    {"ticker": "BLK",   "name": "블랙록",          "exchange": "NYS"},
    # ── 헬스케어 ─────────────────────────────
    {"ticker": "VRTX",  "name": "버텍스",          "exchange": "NAS"},
    {"ticker": "REGN",  "name": "리제너론",        "exchange": "NAS"},
    {"ticker": "ISRG",  "name": "인튜이티브서지컬", "exchange": "NAS"},
    {"ticker": "MRNA",  "name": "모더나",          "exchange": "NAS"},
    {"ticker": "LLY",   "name": "일라이릴리",      "exchange": "NYS"},
    {"ticker": "JNJ",   "name": "존슨앤존슨",      "exchange": "NYS"},
    {"ticker": "UNH",   "name": "유나이티드헬스",  "exchange": "NYS"},
    {"ticker": "PFE",   "name": "화이자",          "exchange": "NYS"},
    {"ticker": "ABBV",  "name": "애브비",          "exchange": "NYS"},
    {"ticker": "MRK",   "name": "머크",            "exchange": "NYS"},
    {"ticker": "TMO",   "name": "써모피셔",        "exchange": "NYS"},
    {"ticker": "DHR",   "name": "다나허",          "exchange": "NYS"},
    {"ticker": "AMGN",  "name": "암젠",            "exchange": "NAS"},
    {"ticker": "GILD",  "name": "길리어드",        "exchange": "NAS"},
    # ── 소비재 / 산업 ───────────────────────
    {"ticker": "SBUX",  "name": "스타벅스",        "exchange": "NAS"},
    {"ticker": "NKE",   "name": "나이키",          "exchange": "NYS"},
    {"ticker": "DIS",   "name": "디즈니",          "exchange": "NYS"},
    {"ticker": "WMT",   "name": "월마트",          "exchange": "NYS"},
    {"ticker": "COST",  "name": "코스트코",        "exchange": "NAS"},
    {"ticker": "MCD",   "name": "맥도날드",        "exchange": "NYS"},
    {"ticker": "HD",    "name": "홈디포",          "exchange": "NYS"},
    {"ticker": "LOW",   "name": "로우스",          "exchange": "NYS"},
    {"ticker": "PG",    "name": "P&G",             "exchange": "NYS"},
    {"ticker": "KO",    "name": "코카콜라",        "exchange": "NYS"},
    {"ticker": "PEP",   "name": "펩시",            "exchange": "NAS"},
    {"ticker": "TGT",   "name": "타깃",            "exchange": "NYS"},
    {"ticker": "BKNG",  "name": "부킹홀딩스",      "exchange": "NAS"},
    {"ticker": "MAR",   "name": "메리어트",        "exchange": "NAS"},
    {"ticker": "F",     "name": "포드",            "exchange": "NYS"},
    {"ticker": "GM",    "name": "GM",              "exchange": "NYS"},
    {"ticker": "RIVN",  "name": "리비안",          "exchange": "NAS"},
    {"ticker": "LCID",  "name": "루시드",          "exchange": "NAS"},
    # ── 산업/방산/우주 ─────────────────────
    {"ticker": "BA",    "name": "보잉",            "exchange": "NYS"},
    {"ticker": "CAT",   "name": "캐터필러",        "exchange": "NYS"},
    {"ticker": "GE",    "name": "GE",              "exchange": "NYS"},
    {"ticker": "RTX",   "name": "레이시온",        "exchange": "NYS"},
    {"ticker": "LMT",   "name": "록히드마틴",      "exchange": "NYS"},
    {"ticker": "DE",    "name": "디어",            "exchange": "NYS"},
    # ── 통신 / 미디어 ───────────────────────
    {"ticker": "T",     "name": "AT&T",            "exchange": "NYS"},
    {"ticker": "VZ",    "name": "버라이즌",        "exchange": "NYS"},
    {"ticker": "TMUS",  "name": "T모바일",         "exchange": "NAS"},
    {"ticker": "CMCSA", "name": "컴캐스트",        "exchange": "NAS"},
    # ── 에너지 ───────────────────────────
    {"ticker": "XOM",   "name": "엑손모빌",        "exchange": "NYS"},
    {"ticker": "CVX",   "name": "셰브론",          "exchange": "NYS"},
    {"ticker": "OXY",   "name": "옥시덴탈",        "exchange": "NYS"},
    # ── China ADR (옵션) ────────────────────
    {"ticker": "BABA",  "name": "알리바바",        "exchange": "NYS"},
    {"ticker": "JD",    "name": "징둥",            "exchange": "NAS"},
    {"ticker": "PDD",   "name": "핀둬둬",          "exchange": "NAS"},
    {"ticker": "BIDU",  "name": "바이두",          "exchange": "NAS"},
    {"ticker": "NIO",   "name": "니오",            "exchange": "NYS"},
    # ── 인덱스 / 테마 ETF ────────────────────────────────
    {"ticker": "QQQ",   "name": "나스닥100 ETF",   "exchange": "NAS"},
    {"ticker": "SPY",   "name": "S&P500 ETF",      "exchange": "AMS"},
    {"ticker": "ARKK",  "name": "ARK이노베이션",   "exchange": "AMS"},
    {"ticker": "SOXX",  "name": "반도체 ETF",      "exchange": "NAS"},
    {"ticker": "XLK",   "name": "기술주 ETF",      "exchange": "AMS"},
    {"ticker": "XLF",   "name": "금융 ETF",        "exchange": "AMS"},
    {"ticker": "XLE",   "name": "에너지 ETF",      "exchange": "AMS"},
    {"ticker": "XLV",   "name": "헬스케어 ETF",    "exchange": "AMS"},
    {"ticker": "XLI",   "name": "산업 ETF",        "exchange": "AMS"},
    {"ticker": "XLP",   "name": "필수소비 ETF",    "exchange": "AMS"},
    {"ticker": "XLY",   "name": "임의소비 ETF",    "exchange": "AMS"},
    {"ticker": "IWM",   "name": "러셀2000 ETF",    "exchange": "AMS"},
    {"ticker": "DIA",   "name": "다우 ETF",        "exchange": "AMS"},
    # ── v6.15 추가: 미드캡 성장주 / AI 테마 / 바이오 ──
    {"ticker": "DELL",  "name": "델",              "exchange": "NYS"},
    {"ticker": "HPQ",   "name": "HP",              "exchange": "NYS"},
    {"ticker": "IBM",   "name": "IBM",             "exchange": "NYS"},
    {"ticker": "CSCO",  "name": "시스코",          "exchange": "NAS"},
    {"ticker": "ADSK",  "name": "오토데스크",      "exchange": "NAS"},
    {"ticker": "CDNS",  "name": "케이던스",        "exchange": "NAS"},
    {"ticker": "SNPS",  "name": "시놉시스",        "exchange": "NAS"},
    {"ticker": "ANSS",  "name": "ANSYS",           "exchange": "NAS"},
    {"ticker": "ROP",   "name": "로퍼",            "exchange": "NYS"},
    {"ticker": "FSLR",  "name": "퍼스트솔라",      "exchange": "NAS"},
    {"ticker": "ENPH",  "name": "엔페이즈",        "exchange": "NAS"},
    {"ticker": "PLUG",  "name": "플러그파워",      "exchange": "NAS"},
    {"ticker": "CHWY",  "name": "츄이",            "exchange": "NYS"},
    {"ticker": "PINS",  "name": "핀터레스트",      "exchange": "NYS"},
    {"ticker": "SNAP",  "name": "스냅",            "exchange": "NYS"},
    {"ticker": "SPOT",  "name": "스포티파이",      "exchange": "NYS"},
    {"ticker": "DKNG",  "name": "드래프트킹스",    "exchange": "NAS"},
    {"ticker": "CPNG",  "name": "쿠팡",            "exchange": "NYS"},
    # ── 바이오 미드캡 ─────────────────────
    {"ticker": "BIIB",  "name": "바이오젠",        "exchange": "NAS"},
    {"ticker": "ILMN",  "name": "일루미나",        "exchange": "NAS"},
    {"ticker": "BMY",   "name": "BMS",             "exchange": "NYS"},
    {"ticker": "CI",    "name": "시그나",          "exchange": "NYS"},
    {"ticker": "CVS",   "name": "CVS헬스",         "exchange": "NYS"},
    {"ticker": "ELV",   "name": "엘레반스",        "exchange": "NYS"},
    {"ticker": "HUM",   "name": "휴마나",          "exchange": "NYS"},
    {"ticker": "MCK",   "name": "맥케슨",          "exchange": "NYS"},
    # ── 산업/소재 ────────────────────────
    {"ticker": "HON",   "name": "허니웰",          "exchange": "NAS"},
    {"ticker": "UPS",   "name": "UPS",             "exchange": "NYS"},
    {"ticker": "FDX",   "name": "FedEx",           "exchange": "NYS"},
    {"ticker": "MMM",   "name": "3M",              "exchange": "NYS"},
    {"ticker": "EMR",   "name": "에머슨",          "exchange": "NYS"},
    {"ticker": "ETN",   "name": "이튼",            "exchange": "NYS"},
    {"ticker": "ITW",   "name": "ITW",             "exchange": "NYS"},
    {"ticker": "FCX",   "name": "프리포트",        "exchange": "NYS"},
    {"ticker": "NEM",   "name": "뉴몬트",          "exchange": "NYS"},
    {"ticker": "GLD",   "name": "금 ETF",          "exchange": "AMS"},
    # ── 부동산 / REIT ───────────────────
    {"ticker": "AMT",   "name": "아메리칸타워",    "exchange": "NYS"},
    {"ticker": "PLD",   "name": "프롤로지스",      "exchange": "NYS"},
    {"ticker": "EQIX",  "name": "에퀴닉스",        "exchange": "NAS"},
    # ── 신성장 / 미드캡 (액션 큰 이름) ──
    {"ticker": "PATH",  "name": "유아이패스",      "exchange": "NYS"},
    {"ticker": "DOCN",  "name": "디지털오션",      "exchange": "NYS"},
    {"ticker": "BILL",  "name": "빌닷컴",          "exchange": "NYS"},
    {"ticker": "TWLO",  "name": "트윌리오",        "exchange": "NYS"},
    {"ticker": "U",     "name": "유니티",          "exchange": "NYS"},
    {"ticker": "RDDT",  "name": "레딧",            "exchange": "NYS"},
    {"ticker": "APP",   "name": "앱러빈",          "exchange": "NAS"},
    {"ticker": "DASH",  "name": "도어대시",        "exchange": "NYS"},
]


def scan_overseas_candidates(exclude_tickers: list = None) -> list:
    if exclude_tickers is None:
        exclude_tickers = []

    regime_info = get_os_regime()
    regime = regime_info["regime"]

    if regime == "BEAR":
        print(f"[OS_SCANNER] 국면 BEAR → 신규 진입 보류")
        return []

    # v6.2: 소수점 매매 활성시 가격 필터 미적용 (분수주 매수 가능)
    try:
        from config import US_FRACTIONAL_ENABLED as _frac
    except ImportError:
        _frac = False

    candidates = []
    for stock in OS_UNIVERSE:
        ticker = stock["ticker"]
        if ticker in exclude_tickers:
            continue

        curr = get_overseas_current(ticker, stock["exchange"])
        if not curr or curr["price"] == 0:
            continue
        # 정수 매매시만 가격 > 예산 종목 자동 스킵
        if not _frac and curr["price"] > OS_POSITION_USD:
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


# v6.1: 진단 — 유니버스 각 종목이 왜 탈락했는지 한눈에
# v6.4: progress_callback 으로 진행률 텔레그램 갱신, sample_size 로 빠른 진단
def diagnose_overseas(sample_size: int | None = None,
                      progress_callback=None) -> dict:
    """모든 유니버스 종목의 진입 가능 상태를 진단.

    Returns: {
        "regime": "BULL/SIDEWAYS/BEAR",
        "qqq_panic": bool,
        "results": [
            {"ticker", "name", "price", "status", "reason", "metrics?"},
            ...
        ],
        "summary": {status: count, ...}
    }
    status 값:
        "pass"        : 진입 조건 모두 통과
        "no_data"     : 가격 조회 실패
        "budget"      : 가격 > OS_POSITION_USD
        "ma_align"    : MA50 ≤ MA200 (정배열 X)
        "ma20"        : 종가 ≤ MA20
        "rsi"         : RSI 범위 밖
        "volume"      : 거래량 부족
        "pattern"     : 브레이크아웃/되돌림 X
        "data_short"  : 일봉 부족
        "error"       : 예외 발생
    """
    regime_info = get_os_regime()
    regime = regime_info["regime"]
    qqq_panic = False
    try:
        from strategy_overseas import check_qqq_panic
        qqq_panic = check_qqq_panic()
    except Exception:
        pass

    # v6.2: 소수점 매매시 가격 필터 미적용
    try:
        from config import US_FRACTIONAL_ENABLED as _frac
    except ImportError:
        _frac = False

    results = []
    summary = {}

    # v6.4: 빠른 진단 모드 — 처음 sample_size 종목만 (rate limit / 시간 절약)
    universe = OS_UNIVERSE[:sample_size] if sample_size else OS_UNIVERSE
    total = len(universe)

    for idx, stock in enumerate(universe, 1):
        # v6.4: 매 10종목마다 진행률 콜백
        if progress_callback and idx % 10 == 1:
            try:
                progress_callback(idx, total)
            except Exception:
                pass
        ticker = stock["ticker"]
        name = stock["name"]
        exchange = stock["exchange"]
        entry: dict = {"ticker": ticker, "name": name, "exchange": exchange}

        try:
            curr = get_overseas_current(ticker, exchange)
            if not curr or curr.get("price", 0) == 0:
                entry["price"] = 0.0
                entry["status"] = "no_data"
                entry["reason"] = "현재가 조회 실패"
                results.append(entry)
                summary["no_data"] = summary.get("no_data", 0) + 1
                continue

            price = curr["price"]
            entry["price"] = price

            if not _frac and price > OS_POSITION_USD:
                entry["status"] = "budget"
                entry["reason"] = f"${price:.2f} > 예산 ${OS_POSITION_USD}"
                results.append(entry)
                summary["budget"] = summary.get("budget", 0) + 1
                continue

            ok, reason, metrics = check_os_entry(ticker, exchange, name)
            entry["metrics"] = metrics
            if ok:
                entry["status"] = "pass"
                entry["reason"] = reason
                summary["pass"] = summary.get("pass", 0) + 1
            else:
                # 사유 분류
                if "일봉 부족" in reason:
                    s = "data_short"
                elif "MA50" in reason and "≤" in reason:
                    s = "ma_align"
                elif "MA20" in reason:
                    s = "ma20"
                elif "RSI" in reason:
                    s = "rsi"
                elif "거래량" in reason:
                    s = "volume"
                elif "패턴" in reason or "브레이크" in reason:
                    s = "pattern"
                else:
                    s = "other"
                entry["status"] = s
                entry["reason"] = reason
                summary[s] = summary.get(s, 0) + 1
            results.append(entry)
        except Exception as e:
            entry["status"] = "error"
            entry["reason"] = f"{type(e).__name__}: {str(e)[:50]}"
            results.append(entry)
            summary["error"] = summary.get("error", 0) + 1

    return {
        "regime":   regime,
        "qqq_panic": qqq_panic,
        "results":  results,
        "summary":  summary,
        "universe_size": total,
        "universe_full": len(OS_UNIVERSE),
        "sampled":  total < len(OS_UNIVERSE),
        "budget_usd": OS_POSITION_USD,
    }


def format_diagnose_msg(d: dict) -> str:
    """diagnose_overseas() 결과 → 텔레그램 메시지."""
    if not d:
        return "🔍 US 스캔 진단 — 데이터 없음"

    # v6.16: summary 카운트도 메시지 헤더에 추가
    regime = d.get("regime", "?")
    panic = d.get("qqq_panic", False)
    summary = d.get("summary", {})
    results = d.get("results", [])
    universe = d.get("universe_size", 0)
    full_size = d.get("universe_full", universe)
    budget = d.get("budget_usd", 0)
    sampled = d.get("sampled", False)

    regime_icon = {"BULL": "🟢", "SIDEWAYS": "🟡", "BEAR": "🔴"}.get(regime, "⚪")
    panic_str = " ⚠️QQQ패닉" if panic else ""
    size_str = f"{universe}/{full_size}종 샘플" if sampled else f"{universe}종"

    header = (
        f"🔍 <b>US 스캔 진단</b> ({size_str}, 1주 예산 ${budget})\n"
        f"국면: {regime_icon} {regime}{panic_str}"
    )
    if regime == "BEAR":
        header += "\n→ BEAR 차단 — 신규 진입 보류 (regime 회복 대기)"

    # 카테고리별 그룹
    groups = {
        "pass":       ("✅ 통과",     []),
        "budget":     ("💰 예산초과", []),
        "ma_align":   ("📉 정배열X",  []),
        "ma20":       ("📊 MA20하향", []),
        "rsi":        ("🔥 RSI범위밖", []),
        "volume":     ("🔇 거래량부족", []),
        "pattern":    ("📐 패턴X",    []),
        "data_short": ("📦 일봉부족", []),
        "no_data":    ("❌ 데이터X",  []),
        "error":      ("⚠️  오류",   []),
        "other":      ("❓ 기타",     []),
    }

    for r in results:
        s = r.get("status", "other")
        if s not in groups:
            s = "other"
        if s == "pass":
            groups[s][1].append(f"{r['ticker']} ${r.get('price', 0):.0f} {r.get('reason', '')}")
        elif s == "budget":
            groups[s][1].append(f"{r['ticker']}(${r.get('price', 0):.0f})")
        elif s == "rsi":
            m = r.get("metrics", {})
            groups[s][1].append(f"{r['ticker']}({int(m.get('rsi', 0))})")
        else:
            groups[s][1].append(r["ticker"])

    lines = [header, ""]
    # pass 먼저, 나머지는 카운트 많은 순
    if groups["pass"][1]:
        label, items = groups["pass"]
        lines.append(f"<b>{label}</b> ({len(items)}):")
        for it in items[:8]:
            lines.append(f"   {it}")
        if len(items) > 8:
            lines.append(f"   ... +{len(items) - 8}")
        lines.append("")

    # 나머지 (카운트 많은 순)
    other_keys = sorted(
        [k for k in groups if k != "pass"],
        key=lambda k: -len(groups[k][1]),
    )
    for k in other_keys:
        label, items = groups[k]
        if not items:
            continue
        # 한 줄 표시 (티커만)
        joined = ", ".join(items[:15])
        if len(items) > 15:
            joined += f", ... +{len(items) - 15}"
        lines.append(f"{label} ({len(items)}): {joined}")

    return "\n".join(lines)

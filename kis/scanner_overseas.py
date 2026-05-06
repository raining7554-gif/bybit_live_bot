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


# v6.1: 진단 — 유니버스 각 종목이 왜 탈락했는지 한눈에
def diagnose_overseas() -> dict:
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

    results = []
    summary = {}

    for stock in OS_UNIVERSE:
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

            if price > OS_POSITION_USD:
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
        "universe_size": len(OS_UNIVERSE),
        "budget_usd": OS_POSITION_USD,
    }


def format_diagnose_msg(d: dict) -> str:
    """diagnose_overseas() 결과 → 텔레그램 메시지."""
    if not d:
        return "🔍 US 스캔 진단 — 데이터 없음"

    regime = d.get("regime", "?")
    panic = d.get("qqq_panic", False)
    summary = d.get("summary", {})
    results = d.get("results", [])
    universe = d.get("universe_size", 0)
    budget = d.get("budget_usd", 0)

    regime_icon = {"BULL": "🟢", "SIDEWAYS": "🟡", "BEAR": "🔴"}.get(regime, "⚪")
    panic_str = " ⚠️QQQ패닉" if panic else ""

    header = (
        f"🔍 <b>US 스캔 진단</b> (유니버스 {universe}종, 1주 예산 ${budget})\n"
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

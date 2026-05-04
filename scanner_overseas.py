"""나스닥 스캐너 v3.0 — 메가캡 + AI 대장주 스윙

유니버스 10종목에 대해 일봉 기준 조건 체크.
소수점 매매 안 함 (1주 이상만 진입 가능).
"""
from config import OS_POSITION_USD
from strategy_overseas import get_os_regime, check_os_entry, get_overseas_current

# 메가캡 + AI/반도체 핵심 10종목
OS_UNIVERSE = [
    {"ticker": "NVDA",  "name": "엔비디아",     "exchange": "NAS"},
    {"ticker": "MSFT",  "name": "마이크로소프트","exchange": "NAS"},
    {"ticker": "GOOGL", "name": "알파벳",       "exchange": "NAS"},
    {"ticker": "META",  "name": "메타",         "exchange": "NAS"},
    {"ticker": "AVGO",  "name": "브로드컴",     "exchange": "NAS"},
    {"ticker": "AMD",   "name": "AMD",          "exchange": "NAS"},
    {"ticker": "TSM",   "name": "TSMC",         "exchange": "NYS"},
    {"ticker": "PLTR",  "name": "팔란티어",     "exchange": "NAS"},
    {"ticker": "CRWD",  "name": "크라우드스트라이크","exchange": "NAS"},
    {"ticker": "QQQ",   "name": "나스닥ETF",    "exchange": "NAS"},
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

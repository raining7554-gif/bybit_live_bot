"""스캐너 v3.0 — 섹터 모멘텀 → 유니버스 필터 → 스윙 진입 조건"""
from strategy import get_market_regime, check_swing_entry
from sector_detector import get_top_sectors
from universe_filter import get_universe_for_sectors


def scan_candidates(exclude_tickers: list = None) -> list:
    if exclude_tickers is None:
        exclude_tickers = []

    regime_info = get_market_regime()
    regime = regime_info["regime"]

    # 하락장/폭락장: 신규 진입 보류
    if regime in ("BEAR", "CRASH"):
        print(f"[SCANNER] 국면={regime} → 신규 진입 보류")
        return []

    # 횡보장: 섹터 강세 기준 완화 (0.2%)
    min_sec_change = 0.2 if regime == "SIDEWAYS" else 0.5

    # ── 1단계: 강세 섹터 top 3 ─────────────────────────
    top_sectors = get_top_sectors(n=3, min_change=min_sec_change)
    if not top_sectors:
        print("[SCANNER] 강세 섹터 없음 → 스캔 종료")
        return []

    sector_keys = [s["sector"] for s in top_sectors]

    # ── 2단계: 해당 섹터 유니버스 ───────────────────────
    universe = get_universe_for_sectors(sector_keys)
    universe = [u for u in universe if u["ticker"] not in exclude_tickers]

    if not universe:
        print("[SCANNER] 유니버스 비었음")
        return []

    # ── 3단계: 스윙 진입 조건 체크 (일봉) ───────────────
    candidates = []
    for item in universe:
        ok, reason, metrics = check_swing_entry(item["ticker"], item["name"])
        if not ok:
            print(f"[SCANNER] ❌ {item['name']}({item['ticker']}) {reason}")
            continue

        candidates.append({
            "ticker": item["ticker"],
            "name": item["name"],
            "price": item["price"],
            "sector": item["sector"],
            "change_rate": item["change_rate"],
            "reason": reason,
            "regime": regime,
            "strategy_type": "SWING",
            "metrics": metrics,
        })
        print(f"[SCANNER] ✅ {item['name']}({item['ticker']}) [{item['sector']}] {reason}")

    # 섹터 1등 우선 → 당일 등락률 높은 순
    sector_rank = {s["sector"]: i for i, s in enumerate(top_sectors)}
    candidates.sort(
        key=lambda x: (sector_rank.get(x["sector"], 99), -x["change_rate"])
    )
    print(f"[SCANNER] 완료 - {len(candidates)}개 후보")
    return candidates


# ── 레거시 호환 ───────────────────────────────────────
def get_top_volume_stocks() -> list:
    return []


def get_stock_detail(ticker: str) -> dict:
    from universe_filter import _get_detail
    return _get_detail(ticker)

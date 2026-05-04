"""섹터 모멘텀 감지 v1.0

KOSPI/KOSDAQ 대표 섹터 ETF 당일 등락률을 조회해서 강세 섹터 top N 반환.
업종지수 API는 TR 권한 이슈가 잦아, 섹터별 대표 ETF 현재가 조회로 대체.
"""
import kis_auth as api

# 섹터별 대표 ETF (등락률이 곧 그 섹터 강도의 프록시)
SECTOR_ETFS = {
    "반도체":   {"ticker": "091160", "name": "KODEX 반도체"},
    "AI_SW":    {"ticker": "314250", "name": "KODEX Fn웹툰메타버스"},  # AI/SW 대용
    "2차전지":  {"ticker": "305540", "name": "TIGER 2차전지테마"},
    "바이오":   {"ticker": "244580", "name": "KODEX 바이오"},
    "조선":     {"ticker": "466920", "name": "KODEX K-조선"},
    "방산":     {"ticker": "449450", "name": "TIGER K방산"},
    "원전":     {"ticker": "465350", "name": "TIGER 원자력"},
    "자동차":   {"ticker": "091180", "name": "KODEX 자동차"},
    "인터넷":   {"ticker": "157490", "name": "TIGER 소프트웨어"},
    "금융":     {"ticker": "091170", "name": "KODEX 은행"},
}


def _get_price_info(ticker: str) -> dict:
    """주식/ETF 현재가 및 등락률 조회"""
    try:
        data = api.get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
        )
        if data.get("rt_cd") == "0":
            o = data.get("output", {})
            return {
                "price": float(o.get("stck_prpr", 0)),
                "change_rate": float(o.get("prdy_ctrt", 0)),
                "volume": int(o.get("acml_vol", 0)),
            }
    except Exception as e:
        print(f"[SECTOR] {ticker} 조회 오류: {e}")
    return {}


def get_sector_strengths() -> list:
    """섹터별 당일 등락률 내림차순 정렬"""
    results = []
    for sector_key, info in SECTOR_ETFS.items():
        p = _get_price_info(info["ticker"])
        if not p:
            continue
        results.append({
            "sector": sector_key,
            "etf_name": info["name"],
            "etf_ticker": info["ticker"],
            "change_rate": p["change_rate"],
            "price": p["price"],
        })
    results.sort(key=lambda x: x["change_rate"], reverse=True)
    return results


def get_top_sectors(n: int = 3, min_change: float = 0.3) -> list:
    """상위 n개 섹터 중 등락률이 min_change% 이상인 것만 반환"""
    strengths = get_sector_strengths()
    top = [s for s in strengths[:n] if s["change_rate"] >= min_change]
    if top:
        summary = ", ".join(f"{s['sector']}({s['change_rate']:+.1f}%)" for s in top)
        print(f"[SECTOR] 강세 섹터 {len(top)}개: {summary}")
    else:
        print(f"[SECTOR] 강세 섹터 없음 (모두 {min_change}% 미만)")
    return top

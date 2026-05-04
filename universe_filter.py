"""유니버스 자동 필터링 v1.0

섹터별 후보 종목 풀에서 가격·상태·유동성 조건을 만족하는 종목만 선별.
시드가 작으므로 1주라도 살 수 있는 가격대로 자동 제한.
"""
import kis_auth as api
from config import DOM_UNIVERSE_MAX_PRICE, DOM_UNIVERSE_MIN_PRICE

# 섹터별 후보 종목 (넓게 잡고 가격 필터가 걸러냄)
# 대장주(삼성전자/하이닉스/LG엔솔 등)는 시드 부족해 자동 제외됨
SECTOR_CANDIDATES = {
    "반도체": [
        ("000660", "SK하이닉스"), ("005930", "삼성전자"),
        ("042700", "한미반도체"), ("240810", "원익IPS"),
        ("039030", "이오테크닉스"), ("005290", "동진쎄미켐"),
        ("357780", "솔브레인"), ("058470", "리노공업"),
        ("000990", "DB하이텍"), ("036930", "주성엔지니어링"),
        ("403870", "HPSP"), ("140860", "파크시스템스"),
        ("094840", "슈프리마"), ("095340", "ISC"),
        ("064290", "인텍플러스"), ("131970", "테스나"),
        ("036810", "에프에스티"), ("104830", "원익머트리얼즈"),
    ],
    "AI_SW": [
        ("086390", "유니슨"), ("253450", "스튜디오드래곤"),
        ("064850", "더존비즈온"), ("108860", "셀바스AI"),
        ("025770", "한국정보통신"), ("035420", "NAVER"),
        ("035720", "카카오"), ("060280", "큐렉소"),
        ("203650", "드림시큐리티"), ("376300", "디어유"),
    ],
    "2차전지": [
        ("247540", "에코프로비엠"), ("066970", "엘앤에프"),
        ("003670", "포스코퓨처엠"), ("096770", "SK이노베이션"),
        ("373220", "LG에너지솔루션"), ("006400", "삼성SDI"),
        ("005490", "POSCO홀딩스"), ("086520", "에코프로"),
        ("121600", "나노신소재"), ("020150", "롯데에너지머티리얼즈"),
    ],
    "바이오": [
        ("207940", "삼성바이오로직스"), ("068270", "셀트리온"),
        ("196170", "알테오젠"), ("328130", "루닛"),
        ("214150", "클래시스"), ("237690", "에스티팜"),
        ("298380", "에이비엘바이오"), ("085660", "차바이오텍"),
    ],
    "조선": [
        ("329180", "HD현대중공업"), ("010620", "HD현대미포"),
        ("009540", "HD한국조선해양"), ("042660", "한화오션"),
        ("010140", "삼성중공업"),
    ],
    "방산": [
        ("012450", "한화에어로스페이스"), ("079550", "LIG넥스원"),
        ("064350", "현대로템"), ("272210", "한화시스템"),
    ],
    "원전": [
        ("034020", "두산에너빌리티"), ("052690", "한전기술"),
        ("015760", "한국전력"),
    ],
    "자동차": [
        ("005380", "현대차"), ("000270", "기아"),
        ("012330", "현대모비스"), ("161390", "한국타이어앤테크놀로지"),
    ],
    "인터넷": [
        ("035420", "NAVER"), ("035720", "카카오"),
        ("376300", "디어유"),
    ],
    "금융": [
        ("055550", "신한지주"), ("105560", "KB금융"),
        ("086790", "하나금융지주"), ("316140", "우리금융지주"),
    ],
}


def _get_detail(ticker: str) -> dict:
    try:
        data = api.get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
        )
        if data.get("rt_cd") == "0":
            return data.get("output", {})
    except Exception:
        pass
    return {}


def get_sector_universe(sector_key: str, max_price: int = None) -> list:
    """특정 섹터의 유효 종목 유니버스 반환"""
    if max_price is None:
        max_price = DOM_UNIVERSE_MAX_PRICE

    candidates = SECTOR_CANDIDATES.get(sector_key, [])
    universe = []

    for ticker, name in candidates:
        d = _get_detail(ticker)
        if not d:
            continue
        price = int(d.get("stck_prpr", 0))
        stat = str(d.get("iscd_stat_cls_code", "00"))
        vol = int(d.get("acml_vol", 0))
        trade_amount = int(d.get("acml_tr_pbmn", 0))  # 누적 거래대금(원)

        # 종목상태 정상만
        if stat != "00":
            continue
        # 가격 범위
        if price < DOM_UNIVERSE_MIN_PRICE or price > max_price:
            continue
        # 유동성 — 하루 거래대금 10억 이상 (저유동성 회피)
        if trade_amount < 1_000_000_000:
            continue

        universe.append({
            "ticker": ticker,
            "name": name,
            "price": price,
            "sector": sector_key,
            "change_rate": float(d.get("prdy_ctrt", 0)),
            "volume": vol,
        })

    print(f"[UNIVERSE] {sector_key}: {len(candidates)}개 중 {len(universe)}개 통과")
    return universe


def get_universe_for_sectors(sector_keys: list, max_price: int = None) -> list:
    """여러 섹터의 유니버스 합본"""
    all_uni = []
    seen = set()
    for sk in sector_keys:
        for item in get_sector_universe(sk, max_price):
            if item["ticker"] in seen:
                continue
            seen.add(item["ticker"])
            all_uni.append(item)
    return all_uni

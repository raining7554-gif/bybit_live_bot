"""매매 실행 v3.1 — 스윙 고정 포지션 사이징 + 슬리피지 가드"""
import kis_auth as api
import telegram
from config import ACCOUNT_NO, IS_PAPER, DOM_POSITION_PCT, SLIPPAGE_GUARD_PCT


def _acc_parts():
    parts = ACCOUNT_NO.split("-")
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "01")


def get_account_balance() -> dict:
    acc_no, acc_prod = _acc_parts()
    tr_id = "VTTC8434R" if IS_PAPER else "TTTC8434R"
    try:
        data = api.get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id,
            {
                "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "01",
                "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
            },
        )
        if data.get("rt_cd") == "0":
            o = data.get("output2", [{}])[0]
            return {
                "total_eval": int(o.get("tot_evlu_amt", 0)),
                "available_cash": int(o.get("prvs_rcdl_excc_amt", 0)),
            }
    except Exception as e:
        print(f"[TRADER] 잔고 조회 오류: {e}")
    return {"total_eval": 0, "available_cash": 0}


def buy_market(ticker: str, name: str, reason: str = "스윙 진입",
               expected_price: int | None = None) -> dict | None:
    acc_no, acc_prod = _acc_parts()
    tr_id = "VTTC0802U" if IS_PAPER else "TTTC0802U"

    price_data = api.get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
    )
    current_price = int(price_data.get("output", {}).get("stck_prpr", 0))
    if current_price == 0:
        print(f"[TRADER] 현재가 조회 실패: {ticker}")
        return None

    # 슬리피지 가드: 스캔 시점 대비 SLIPPAGE_GUARD_PCT 초과 급등 시 매수 취소
    if expected_price and expected_price > 0:
        drift = (current_price - expected_price) / expected_price
        if drift > SLIPPAGE_GUARD_PCT:
            msg = f"슬리피지 {drift*100:+.2f}% — {name}({ticker}) 매수 스킵"
            print(f"[TRADER] {msg}")
            telegram.send_error(msg)
            return None

    balance = get_account_balance()
    total = balance["total_eval"]
    available = balance["available_cash"]
    # 소액 시드 모드: 가용현금 95%, 일반: 총평가의 12.5% (8분산)
    try:
        from config import DOM_SMALL_SEED_MODE, DOM_SMALL_SEED_POSITION_PCT
        position_pct = DOM_SMALL_SEED_POSITION_PCT if DOM_SMALL_SEED_MODE else DOM_POSITION_PCT
    except ImportError:
        position_pct = DOM_POSITION_PCT
    target = min(int(total * position_pct), available)
    qty = target // current_price

    if qty == 0:
        msg = (f"⚠️ 매수 스킵: {name}({ticker})\n"
               f"현재가 ₩{current_price:,} > 종목당 예산 ₩{target:,}\n"
               f"(총평가 ₩{total:,} / 가용 ₩{available:,} / 비중 {position_pct*100:.0f}%)")
        print(f"[TRADER] {msg}")
        telegram.send(msg, dedup_sec=3600)
        return None

    body = {
        "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
        "PDNO": ticker, "ORD_DVSN": "01",
        "ORD_QTY": str(qty), "ORD_UNPR": "0",
    }
    data = api.post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)
    if data.get("rt_cd") == "0":
        amount = current_price * qty
        print(f"[TRADER] 매수: {name}({ticker}) {qty}주 @ {current_price:,}원")
        telegram.send_buy(ticker, name, current_price, qty, amount, reason)
        return {
            "ticker": ticker, "name": name, "qty": qty,
            "buy_price": current_price, "strategy_type": "SWING",
        }
    else:
        msg = f"매수 실패 {name}({ticker}): {data.get('msg1', '')}"
        print(f"[TRADER] {msg}")
        telegram.send_error(msg)
        return None


def sell_market(ticker: str, name: str, qty: int, buy_price: int, reason: str = "청산") -> bool:
    acc_no, acc_prod = _acc_parts()
    tr_id = "VTTC0801U" if IS_PAPER else "TTTC0801U"

    price_data = api.get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
    )
    current_price = int(price_data.get("output", {}).get("stck_prpr", 0))

    body = {
        "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
        "PDNO": ticker, "ORD_DVSN": "01",
        "ORD_QTY": str(qty), "ORD_UNPR": "0",
    }
    data = api.post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)
    if data.get("rt_cd") == "0":
        pnl = (current_price - buy_price) / buy_price * 100 if buy_price else 0
        print(f"[TRADER] 매도: {name}({ticker}) {pnl:+.2f}% - {reason}")
        telegram.send_sell(ticker, name, current_price, qty, pnl, reason)
        return True
    else:
        msg = f"매도 실패 {name}({ticker}): {data.get('msg1', '')}"
        print(f"[TRADER] {msg}")
        telegram.send_error(msg)
        return False

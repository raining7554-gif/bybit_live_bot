"""해외 매매 실행 v3.0 — 고정 달러 포지션 사이징"""
import kis_auth as api
import telegram
from config import ACCOUNT_NO, IS_PAPER, OS_POSITION_USD


def _acc_parts():
    parts = ACCOUNT_NO.split("-")
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "01")


def get_overseas_balance() -> dict:
    acc_no, acc_prod = _acc_parts()
    tr_id = "VTRP6504R" if IS_PAPER else "TTRP6504R"  # 해외주식 잔고 조회
    try:
        data = api.get(
            "/uapi/overseas-stock/v1/trading/inquire-present-balance",
            "CTRP6504R" if not IS_PAPER else "VTRP6504R",
            {
                "CANO": acc_no,
                "ACNT_PRDT_CD": acc_prod,
                "WCRC_FRCR_DVSN_CD": "02",
                "NATN_CD": "840",
                "TR_MKET_CD": "00",
                "INQR_DVSN_CD": "00",
            },
        )
        if data.get("rt_cd") == "0":
            o3 = data.get("output3", {})
            return {
                "total_eval_usd": float(o3.get("tot_asst_amt", 0)),
                "available_usd": float(o3.get("ord_psbl_frcr_amt", 0)),
            }
    except Exception as e:
        print(f"[OS_TRADER] 잔고 조회 오류: {e}")
    return {"total_eval_usd": 0, "available_usd": 0}


def calc_overseas_qty(price_usd: float, budget_override: float | None = None) -> int:
    """종목당 예산 배분, 정수 주식 단위.
    budget_override 지정 시 해당 금액 사용 (레버리지 풀매수용).
    """
    if price_usd <= 0:
        return 0
    balance = get_overseas_balance()
    available = balance["available_usd"]
    budget = budget_override if budget_override else OS_POSITION_USD
    budget = min(budget, available)
    qty = int(budget // price_usd)
    return max(qty, 0)


def buy_overseas(ticker: str, name: str, exchange: str,
                 reason: str = "스윙 진입",
                 full_allocation_usd: float | None = None) -> dict | None:
    acc_no, acc_prod = _acc_parts()
    tr_id = "VTTT1002U" if IS_PAPER else "TTTT1002U"

    price_data = api.get(
        "/uapi/overseas-price/v1/quotations/price",
        "HHDFS00000300",
        {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
    )
    current_price = float(price_data.get("output", {}).get("last", 0))
    if current_price == 0:
        print(f"[OS_TRADER] 현재가 조회 실패: {ticker}")
        return None

    qty = calc_overseas_qty(current_price, budget_override=full_allocation_usd)
    if qty == 0:
        budget = full_allocation_usd or OS_POSITION_USD
        bal = get_overseas_balance()
        msg = (f"⚠️ 해외 매수 스킵: {name}({ticker})\n"
               f"현재가 ${current_price:.2f} > 슬리브 예산 ${budget:.2f}\n"
               f"(가용 ${bal.get('available_usd', 0):.2f})")
        print(f"[OS_TRADER] {msg}")
        telegram.send(msg, dedup_sec=3600)
        return None

    body = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": acc_prod,
        "OVRS_EXCG_CD": exchange,
        "PDNO": ticker,
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": "0",
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": "00",
    }

    data = api.post("/uapi/overseas-stock/v1/trading/order", tr_id, body)
    if data.get("rt_cd") == "0":
        amount = current_price * qty
        print(f"[OS_TRADER] 매수: {name}({ticker}) {qty}주 @ ${current_price:.2f}")
        telegram.send(
            f"🟢 <b>해외 매수 체결</b>\n"
            f"종목: {name} ({ticker})\n"
            f"가격: ${current_price:.2f} × {qty}주\n"
            f"금액: ${amount:.2f}\n"
            f"사유: {reason}",
            dedup_sec=30,
        )
        # monitor 에도 등록
        try:
            import monitor_overseas as mo
            mo.register_os_position(ticker, current_price)
        except Exception:
            pass
        return {
            "ticker": ticker, "name": name, "exchange": exchange,
            "qty": qty, "buy_price": current_price, "market": "overseas",
        }
    else:
        msg = f"해외 매수 실패 {name}({ticker}): {data.get('msg1', '')}"
        print(f"[OS_TRADER] {msg}")
        telegram.send_error(msg)
        return None


def sell_overseas(ticker: str, name: str, exchange: str, qty: int,
                  buy_price: float, reason: str = "청산") -> bool:
    acc_no, acc_prod = _acc_parts()
    tr_id = "VTTT1006U" if IS_PAPER else "TTTT1006U"

    price_data = api.get(
        "/uapi/overseas-price/v1/quotations/price",
        "HHDFS00000300",
        {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
    )
    current_price = float(price_data.get("output", {}).get("last", 0))

    body = {
        "CANO": acc_no,
        "ACNT_PRDT_CD": acc_prod,
        "OVRS_EXCG_CD": exchange,
        "PDNO": ticker,
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": "0",
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": "00",
    }

    data = api.post("/uapi/overseas-stock/v1/trading/order", tr_id, body)
    if data.get("rt_cd") == "0":
        pnl = (current_price - buy_price) / buy_price * 100 if buy_price else 0
        print(f"[OS_TRADER] 매도: {name}({ticker}) {pnl:+.2f}% - {reason}")
        emoji = "💰" if pnl >= 0 else "🔴"
        telegram.send(
            f"{emoji} <b>해외 매도 체결</b>\n"
            f"종목: {name} ({ticker})\n"
            f"가격: ${current_price:.2f} × {qty}주\n"
            f"수익률: {pnl:+.2f}%\n"
            f"사유: {reason}",
            dedup_sec=30,
        )
        return True
    else:
        msg = f"해외 매도 실패 {name}({ticker}): {data.get('msg1', '')}"
        print(f"[OS_TRADER] {msg}")
        telegram.send_error(msg)
        return False

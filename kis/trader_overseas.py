"""해외 매매 실행 v3.0 — 고정 달러 포지션 사이징"""
import kis_auth as api
import telegram
from config import ACCOUNT_NO, IS_PAPER, OS_POSITION_USD

try:
    from intelligence import journal as _journal, agent as _agent
except Exception as _e:
    _journal = _agent = None
    print(f"[OS_TRADER] intelligence import skip: {_e}")


def _safe_float(v, default: float = 0.0) -> float:
    """API 가 빈 문자열/None 돌려줘도 안전하게 0 으로."""
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _get_price_safe(exchange: str, ticker: str) -> float:
    """현재가 조회 — last 비어있으면 base / open / pre 순으로 fallback."""
    try:
        price_data = api.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
        )
    except Exception as e:
        print(f"[OS_TRADER] {ticker} 시세 API 오류: {e}")
        return 0.0
    out = price_data.get("output", {}) if isinstance(price_data, dict) else {}
    for key in ("last", "base", "open", "pre"):
        v = _safe_float(out.get(key))
        if v > 0:
            if key != "last":
                print(f"[OS_TRADER] {ticker} last 비어있어 {key}={v} 사용")
            return v
    print(f"[OS_TRADER] {ticker} 시세 모든 필드 비어있음 → 스킵")
    return 0.0


def _bot_id_for_strategy() -> str:
    try:
        from config import OS_STRATEGY_MODE
        return f"kis_us_{OS_STRATEGY_MODE}"
    except Exception:
        return "kis_us"


def _acc_parts():
    parts = ACCOUNT_NO.split("-")
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "01")


def _query_psamount() -> dict:
    """JTTT3012R 매수가능금액 조회 — 정확한 USD 가용 잔고용.

    CTRP6504R (잔고조회) 의 ord_psbl_frcr_amt 필드는 종종 비어있어
    봇이 0으로 인식. 이 엔드포인트가 매수가능 USD 정확히 반환.
    """
    acc_no, acc_prod = _acc_parts()
    try:
        data = api.get(
            "/uapi/overseas-stock/v1/trading/inquire-psamount",
            "VTTT3007R" if IS_PAPER else "JTTT3007R",
            {
                "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                "OVRS_EXCG_CD": "NASD",
                "OVRS_ORD_UNPR": "0",
                "ITEM_CD": "",
            },
        )
        if data.get("rt_cd") == "0":
            o = data.get("output", {})
            return {
                "ord_psbl_frcr_amt": _safe_float(o.get("ord_psbl_frcr_amt")),
                "ovrs_ord_psbl_amt": _safe_float(o.get("ovrs_ord_psbl_amt")),
                "frcr_ord_psbl_amt1": _safe_float(o.get("frcr_ord_psbl_amt1")),
                "raw": o,
            }
        else:
            print(f"[OS_TRADER] psamount rt_cd={data.get('rt_cd')} "
                  f"msg={data.get('msg1', '')[:120]}")
    except Exception as e:
        print(f"[OS_TRADER] psamount 조회 오류: {e}")
    return {}


def get_overseas_balance() -> dict:
    """v3.5 잔고 조회 — 정확한 가용 USD 사용.

    1) CTRP6504R 로 총평가 (KRW 환산)
    2) JTTT3007R 로 가용 USD (정확)
    3) 실패시 CTRP6504R 의 외화 필드로 fallback
    """
    acc_no, acc_prod = _acc_parts()
    total_eval_usd = 0.0
    available_usd = 0.0
    raw_balance: dict = {}

    # 1) 종합 잔고 (총평가)
    try:
        data = api.get(
            "/uapi/overseas-stock/v1/trading/inquire-present-balance",
            "VTRP6504R" if IS_PAPER else "CTRP6504R",
            {
                "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                "WCRC_FRCR_DVSN_CD": "02",
                "NATN_CD": "840",
                "TR_MKET_CD": "00",
                "INQR_DVSN_CD": "00",
            },
        )
        if data.get("rt_cd") == "0":
            o3 = data.get("output3", {})
            raw_balance = o3
            total_eval_usd = _safe_float(o3.get("tot_asst_amt"))
            # fallback: 외화예치금
            available_usd = (
                _safe_float(o3.get("ord_psbl_frcr_amt"))
                or _safe_float(o3.get("frcr_dncl_amt1"))
                or _safe_float(o3.get("frcr_dncl_amt"))
            )
    except Exception as e:
        print(f"[OS_TRADER] 잔고 조회 오류: {e}")

    # 2) 매수가능 금액으로 가용 USD 정확히 가져오기 (우선 사용)
    psamount = _query_psamount()
    psamount_usd = (
        psamount.get("ord_psbl_frcr_amt", 0)
        or psamount.get("ovrs_ord_psbl_amt", 0)
        or psamount.get("frcr_ord_psbl_amt1", 0)
    )
    if psamount_usd > 0:
        available_usd = psamount_usd

    # 디버그 로그 (가용 0 일 때 무엇이 비어있는지 보이게)
    if available_usd == 0:
        print(f"[OS_TRADER] 가용 USD 0 진단:")
        print(f"  output3 keys: {list(raw_balance.keys())[:15]}")
        print(f"  psamount: {psamount.get('raw', {})}")

    return {
        "total_eval_usd": total_eval_usd,
        "available_usd": available_usd,
    }


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

    current_price = _get_price_safe(exchange, ticker)
    if current_price == 0:
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

    current_price = _get_price_safe(exchange, ticker)

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
        # 공유 학습 모듈에 기록 + AI 사후분석
        if _journal is not None:
            try:
                bot_id = _bot_id_for_strategy()
                pnl_dollar = float((current_price - buy_price) * qty)
                trade_id = _journal.log_trade(
                    bot_id=bot_id, symbol=ticker, side="long",
                    entry_price=float(buy_price),
                    exit_price=float(current_price),
                    size=float(qty), leverage=1.0,
                    pnl=pnl_dollar, pnl_pct=pnl / 100.0,
                    reason=reason, strategy="us",
                    extra={"name": name, "exchange": exchange},
                )
                if _agent is not None:
                    _agent.analyze_trade_async(
                        bot_id=bot_id,
                        trade={
                            "symbol": ticker, "side": "long",
                            "entry_price": buy_price, "exit_price": current_price,
                            "pnl": pnl_dollar, "pnl_pct": pnl / 100.0,
                            "reason": reason, "strategy": "us_leveraged",
                            "leverage": 1.0,
                        },
                        snapshot={"market": "US", "name": name,
                                  "qty": qty, "exchange": exchange},
                        trade_id=trade_id or None,
                        send_telegram=lambda m: telegram.send(m, dedup_sec=30),
                    )
            except Exception as e:
                print(f"[OS_TRADER] intelligence log err: {e}")
        return True
    else:
        msg = f"해외 매도 실패 {name}({ticker}): {data.get('msg1', '')}"
        print(f"[OS_TRADER] {msg}")
        telegram.send_error(msg)
        return False

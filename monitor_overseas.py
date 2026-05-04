"""나스닥 모니터링 v3.0 — 스윙 방어

장중: 하드 손절 -5%, 트레일링 -10%, QQQ 패닉 시 50% 축소
장마감 직전(한국 05:45): MA50 이탈 시 청산
"""
from datetime import date, timedelta
import kis_auth as api
import trader_overseas as ot
from config import OS_STOP_LOSS, OS_TRAIL_DROP
from strategy_overseas import check_qqq_panic, get_overseas_daily


# ticker -> {peak_price, entry_date, panic_reduced}
_state: dict = {}


def get_current_price(ticker: str, exchange: str) -> float:
    try:
        data = api.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
        )
        return float(data.get("output", {}).get("last", 0))
    except Exception:
        return 0.0


def register_os_position(ticker: str, buy_price: float):
    _state[ticker] = {
        "peak": buy_price,
        "entry_date": date.today(),
        "panic_reduced": False,
    }


def unregister_os(ticker: str):
    _state.pop(ticker, None)


def _ensure(ticker, pos):
    if ticker not in _state:
        register_os_position(ticker, pos["buy_price"])


def check_overseas_positions(positions: dict) -> list:
    closed = []
    panic = check_qqq_panic()

    for ticker, pos in list(positions.items()):
        if pos.get("market") != "overseas":
            continue

        current_price = get_current_price(ticker, pos["exchange"])
        if current_price == 0:
            continue

        _ensure(ticker, pos)
        st = _state[ticker]
        if current_price > st["peak"]:
            st["peak"] = current_price

        pnl = (current_price - pos["buy_price"]) / pos["buy_price"]

        # 1) 하드 손절
        if pnl <= -OS_STOP_LOSS:
            if ot.sell_overseas(ticker, pos["name"], pos["exchange"],
                                pos["qty"], pos["buy_price"],
                                f"손절 ({pnl*100:+.2f}%)"):
                closed.append(ticker)
                unregister_os(ticker)
            continue

        # 2) 트레일링 (수익 구간에서만)
        if pnl > 0:
            drop = (current_price - st["peak"]) / st["peak"]
            if drop <= -OS_TRAIL_DROP:
                if ot.sell_overseas(ticker, pos["name"], pos["exchange"],
                                    pos["qty"], pos["buy_price"],
                                    f"트레일링 ({pnl*100:+.2f}% 고점-{abs(drop)*100:.1f}%)"):
                    closed.append(ticker)
                    unregister_os(ticker)
                continue

        # 3) 패닉 방어: QQQ -2% 시 50% 축소 (1회만)
        if panic and not st["panic_reduced"] and pos["qty"] >= 2:
            reduce_qty = pos["qty"] // 2
            if ot.sell_overseas(ticker, pos["name"], pos["exchange"],
                                reduce_qty, pos["buy_price"],
                                f"QQQ 패닉 -2%+ 방어 축소 {reduce_qty}주"):
                pos["qty"] -= reduce_qty
                st["panic_reduced"] = True

    return closed


def check_overseas_eod(positions: dict) -> list:
    """장마감 전 일봉 청산 체크 (MA50 이탈)"""
    closed = []
    for ticker, pos in list(positions.items()):
        if pos.get("market") != "overseas":
            continue

        candles = get_overseas_daily(ticker, pos["exchange"], count=60)
        if len(candles) < 50:
            continue

        closes = [c["close"] for c in candles]
        ma50 = sum(closes[:50]) / 50
        today_close = closes[0]

        if today_close < ma50 * 0.98:  # 2% 버퍼
            if ot.sell_overseas(ticker, pos["name"], pos["exchange"],
                                pos["qty"], pos["buy_price"],
                                f"[EOD] MA50 이탈 ${today_close:.2f} < ${ma50:.2f}"):
                closed.append(ticker)
                unregister_os(ticker)

    return closed


def force_close_overseas(positions: dict):
    """긴급 강제청산 (사용 거의 안 함)"""
    for ticker, pos in list(positions.items()):
        if pos.get("market") != "overseas":
            continue
        ot.sell_overseas(ticker, pos["name"], pos["exchange"],
                         pos["qty"], pos["buy_price"], "긴급 청산")
        unregister_os(ticker)

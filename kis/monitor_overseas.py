"""나스닥 모니터링 v3.0 — 스윙 방어

장중: 하드 손절 -5%, 트레일링 -10%, QQQ 패닉 시 50% 축소
장마감 직전(한국 05:45): MA50 이탈 시 청산
"""
from datetime import date, timedelta
import kis_auth as api
import trader_overseas as ot
from config import OS_STOP_LOSS, OS_TRAIL_DROP
from strategy_overseas import check_qqq_panic, get_overseas_daily


# ticker -> {peak_price, entry_date, panic_reduced, trail_drop, atr_pct}
_state: dict = {}


def _compute_adaptive_trail(ticker: str, exchange: str) -> float:
    """v4.0: 종목 ATR 기반 동적 trail 폭 (7~13% 사이).

    저변동 종목은 빠르게 잡고, 고변동 종목은 풀백 견딤.
    """
    try:
        from config import OS_TRAIL_ATR_MULT, OS_TRAIL_MIN, OS_TRAIL_MAX
    except ImportError:
        return OS_TRAIL_DROP  # fallback to fixed
    candles = get_overseas_daily(ticker, exchange, count=20)
    if len(candles) < 14:
        return OS_TRAIL_DROP
    # 14일 ATR 근사
    atrs = []
    for i in range(min(14, len(candles) - 1)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        prev_c = candles[i + 1]["close"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        atrs.append(tr)
    if not atrs:
        return OS_TRAIL_DROP
    atr = sum(atrs) / len(atrs)
    cur_close = candles[0]["close"]
    if cur_close <= 0:
        return OS_TRAIL_DROP
    atr_pct = atr / cur_close
    trail = atr_pct * OS_TRAIL_ATR_MULT
    return max(OS_TRAIL_MIN, min(OS_TRAIL_MAX, trail))


def get_current_price(ticker: str, exchange: str) -> float:
    """현재가. last 가 빈 문자열일 수 있어 fallback (base / open) 까지 시도."""
    try:
        data = api.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": exchange, "SYMB": ticker},
        )
        out = data.get("output", {}) if isinstance(data, dict) else {}
    except Exception:
        return 0.0
    for key in ("last", "base", "open", "pre"):
        v = out.get(key)
        if v is None or v == "":
            continue
        try:
            fv = float(v)
            if fv > 0:
                return fv
        except (ValueError, TypeError):
            continue
    return 0.0


def register_os_position(ticker: str, buy_price: float):
    _state[ticker] = {
        "peak": buy_price,
        "entry_date": date.today(),
        "panic_reduced": False,
    }


def unregister_os(ticker: str):
    _state.pop(ticker, None)


def _ensure(ticker, pos, exchange=None):
    if ticker not in _state:
        register_os_position(ticker, pos["buy_price"])
    # v4.0: trail_drop 가 아직 계산 안 되었으면 ATR 기반으로 계산
    st = _state.get(ticker, {})
    if "trail_drop" not in st and exchange:
        st["trail_drop"] = _compute_adaptive_trail(ticker, exchange)


def _check_partial_tp_us(ticker: str, pos: dict, current_price: float) -> bool:
    """v4.0: 미장 단계별 부분 익절. KR 와 동일 로직."""
    try:
        from config import PARTIAL_TP_LEVELS
    except ImportError:
        return False
    buy = pos.get("buy_price", 0)
    qty = pos.get("qty", 0)
    if buy <= 0 or qty <= 0:
        return False
    pnl = (current_price - buy) / buy

    if "original_qty" not in pos:
        pos["original_qty"] = qty
    if "tp_levels_hit" not in pos:
        pos["tp_levels_hit"] = []

    for level_pct, sell_ratio in PARTIAL_TP_LEVELS:
        if level_pct in pos["tp_levels_hit"]:
            continue
        if pnl >= level_pct:
            sell_qty = max(1, int(pos["original_qty"] * sell_ratio))
            sell_qty = min(sell_qty, pos["qty"])
            if sell_qty <= 0:
                continue
            if ot.sell_overseas(
                ticker, pos.get("name", ticker), pos["exchange"],
                sell_qty, buy,
                f"부분익절 +{level_pct*100:.0f}% ({pnl*100:+.2f}%)"
            ):
                pos["qty"] -= sell_qty
                pos["tp_levels_hit"].append(level_pct)
                if pos["qty"] <= 0:
                    return True
            break
    return False


def check_overseas_positions(positions: dict) -> list:
    closed = []
    panic = check_qqq_panic()

    for ticker, pos in list(positions.items()):
        if pos.get("market") != "overseas":
            continue

        current_price = get_current_price(ticker, pos["exchange"])
        if current_price == 0:
            continue

        # v4.0: 단계별 부분 익절
        if _check_partial_tp_us(ticker, pos, current_price):
            closed.append(ticker)
            unregister_os(ticker)
            continue

        _ensure(ticker, pos, exchange=pos["exchange"])
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

        # 2) 트레일링 (수익 구간에서만, v4.0 적응형)
        if pnl > 0:
            drop = (current_price - st["peak"]) / st["peak"]
            adaptive_trail = st.get("trail_drop", OS_TRAIL_DROP)
            if drop <= -adaptive_trail:
                if ot.sell_overseas(ticker, pos["name"], pos["exchange"],
                                    pos["qty"], pos["buy_price"],
                                    f"트레일 ({pnl*100:+.2f}% 고점-{abs(drop)*100:.1f}%, ATR기반 {adaptive_trail*100:.1f}%)"):
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

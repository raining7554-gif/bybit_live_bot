"""모니터링 v3.0 — 스윙 포지션 관리

장중: 하드 손절 + 트레일링 체크 (15초마다)
장마감 직전(15:15): 일봉 청산 조건 체크 (20일선 이탈/최대 보유일)
"""
from datetime import date
import kis_auth as api
import trader
from strategy import SwingStop, check_eod_exit


# ticker -> SwingStop 인스턴스
_stops: dict = {}
# ticker -> 진입일(date)
_entry_dates: dict = {}


def get_current_price(ticker: str) -> int:
    try:
        data = api.get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
        )
        return int(data.get("output", {}).get("stck_prpr", 0))
    except Exception:
        return 0


def register_position(ticker: str, buy_price: float, strategy_type: str = "SWING"):
    _stops[ticker] = SwingStop(buy_price)
    _entry_dates[ticker] = date.today()


def unregister(ticker: str):
    _stops.pop(ticker, None)
    _entry_dates.pop(ticker, None)


def _ensure_stop(ticker: str, pos: dict):
    if ticker not in _stops:
        _stops[ticker] = SwingStop(pos["buy_price"])
    if ticker not in _entry_dates:
        _entry_dates[ticker] = date.today()


def _hold_days(ticker: str) -> int:
    from market_calendar import is_trading_day
    from datetime import timedelta
    start = _entry_dates.get(ticker)
    if not start:
        return 0
    days = 0
    d = start
    today = date.today()
    while d < today:
        d += timedelta(days=1)
        if is_trading_day(d):
            days += 1
    return days


def _check_partial_tp(ticker: str, pos: dict, current_price: float) -> bool:
    """v4.0: 단계별 부분 익절 (+15/30/50%).

    Returns True if position fully closed (last partial = whole remaining).
    """
    try:
        from config import PARTIAL_TP_LEVELS
    except ImportError:
        return False
    buy = pos.get("buy_price", 0)
    qty = pos.get("qty", 0)
    if buy <= 0 or qty <= 0:
        return False
    pnl = (current_price - buy) / buy

    # 처음이면 original_qty + tp_levels_hit 초기화
    if "original_qty" not in pos:
        pos["original_qty"] = qty
    if "tp_levels_hit" not in pos:
        pos["tp_levels_hit"] = []

    for level_pct, sell_ratio in PARTIAL_TP_LEVELS:
        if level_pct in pos["tp_levels_hit"]:
            continue
        if pnl >= level_pct:
            # 원래 qty 의 sell_ratio 만큼 청산
            sell_qty = max(1, int(pos["original_qty"] * sell_ratio))
            sell_qty = min(sell_qty, pos["qty"])  # 남은 거 초과 X
            if sell_qty <= 0:
                continue
            if trader.sell_market(
                ticker, pos.get("name", ticker), sell_qty, buy,
                f"부분익절 +{level_pct*100:.0f}% ({pnl*100:+.2f}%)"
            ):
                pos["qty"] -= sell_qty
                pos["tp_levels_hit"].append(level_pct)
                if pos["qty"] <= 0:
                    return True  # 완전 청산
            break  # 한 번에 한 레벨만
    return False


def check_positions(positions: dict) -> list:
    """장중 실시간 체크 — SWING 트레일링/손절 + CLENOW 비상 손절 + 단계별 부분 익절."""
    closed = []
    for ticker, pos in list(positions.items()):
        current_price = get_current_price(ticker)
        if current_price == 0:
            continue

        # v4.0: 단계별 부분 익절 (모든 모드 적용)
        fully_closed = _check_partial_tp(ticker, pos, current_price)
        if fully_closed:
            closed.append(ticker)
            unregister(ticker)
            continue

        # v4.0: CLENOW 모드 비상 손절 (-7% 블랙스완 방어)
        if pos.get("strategy_type") == "CLENOW":
            try:
                from config import DOM_CLENOW_EMERGENCY_SL
            except ImportError:
                DOM_CLENOW_EMERGENCY_SL = 0.07
            buy = pos.get("buy_price", 0)
            if buy > 0:
                pnl = (current_price - buy) / buy
                if pnl <= -DOM_CLENOW_EMERGENCY_SL:
                    if trader.sell_market(
                        ticker, pos["name"], pos["qty"], buy,
                        f"비상손절 ({pnl*100:+.2f}%)"
                    ):
                        closed.append(ticker)
                        unregister(ticker)
            continue  # CLENOW: 비상 손절 외에는 EOD MA50 만

        # SWING 모드: 트레일링 + 하드 손절
        _ensure_stop(ticker, pos)
        stop = _stops[ticker]
        should_close, reason = stop.update_intraday(current_price)

        if should_close:
            if trader.sell_market(ticker, pos["name"], pos["qty"], pos["buy_price"], reason):
                closed.append(ticker)
                unregister(ticker)
    return closed


def check_eod(positions: dict) -> list:
    """일봉 기준 청산 체크 (장마감 직전 1회)"""
    closed = []
    for ticker, pos in list(positions.items()):
        # CLENOW: MA50 이탈 시 청산
        if pos.get("strategy_type") == "CLENOW":
            try:
                import strategy_clenow_kr as clenow
                from config import CLENOW_EXIT_MA
                should_exit, reason = clenow.should_exit(ticker, CLENOW_EXIT_MA)
            except Exception as e:
                print(f"[MONITOR] Clenow 청산 체크 오류 {ticker}: {e}")
                should_exit, reason = False, ""
        else:
            _ensure_stop(ticker, pos)
            hold = _hold_days(ticker)
            should_exit, reason = check_eod_exit(ticker, pos["buy_price"], hold)

        if should_exit:
            full_reason = f"[EOD] {reason}"
            if trader.sell_market(ticker, pos["name"], pos["qty"], pos["buy_price"], full_reason):
                closed.append(ticker)
                unregister(ticker)
    return closed


def force_close_all(positions: dict):
    """긴급 전량 청산 (일반적으로 사용 안 함 — 스윙이므로)"""
    if not positions:
        return
    print("[MONITOR] 긴급 전량 청산")
    for ticker, pos in list(positions.items()):
        trader.sell_market(ticker, pos["name"], pos["qty"], pos["buy_price"], "긴급 청산")
        unregister(ticker)

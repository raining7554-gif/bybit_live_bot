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
    # v6.29: Clenow 보호용 — 고점 + 가격 이력 추적
    _clenow_state[ticker] = {
        "peak": buy_price,
        "price_history": [],  # [(timestamp, price), ...] (last 30 min)
    }


def unregister(ticker: str):
    _stops.pop(ticker, None)
    _entry_dates.pop(ticker, None)
    _clenow_state.pop(ticker, None)


# v6.29: Clenow 종목별 추적 상태 (peak + 가격 이력)
_clenow_state: dict = {}


def _check_clenow_protections(ticker: str, pos: dict, current_price: float) -> tuple[bool, str]:
    """v6.29: Clenow 종목 3중 보호 체크. (should_exit, reason)."""
    import time as _t
    try:
        from config import (
            DOM_CLENOW_EMERGENCY_SL,
            DOM_CLENOW_PEAK_TRAIL_MIN_GAIN, DOM_CLENOW_PEAK_TRAIL_DROP,
            DOM_CLENOW_FLASH_DROP_PCT, DOM_CLENOW_FLASH_DROP_MIN,
        )
    except ImportError:
        return False, ""

    buy = pos.get("buy_price", 0)
    if buy <= 0:
        return False, ""
    pnl = (current_price - buy) / buy

    # 1) 하드 SL (-5%)
    if pnl <= -DOM_CLENOW_EMERGENCY_SL:
        return True, f"비상손절 ({pnl*100:+.2f}%)"

    # state 보장
    if ticker not in _clenow_state:
        _clenow_state[ticker] = {"peak": buy, "price_history": []}
    st = _clenow_state[ticker]

    # 고점 갱신
    if current_price > st["peak"]:
        st["peak"] = current_price

    # 가격 이력 (최근 30분)
    now_ts = _t.time()
    st["price_history"].append((now_ts, current_price))
    cutoff = now_ts - DOM_CLENOW_FLASH_DROP_MIN * 60
    st["price_history"] = [(t, p) for t, p in st["price_history"] if t >= cutoff]

    # 2) 고점 트레일링 (+5% 이상 수익 후 활성)
    peak_gain = (st["peak"] - buy) / buy
    if peak_gain >= DOM_CLENOW_PEAK_TRAIL_MIN_GAIN:
        drop_from_peak = (current_price - st["peak"]) / st["peak"]
        if drop_from_peak <= -DOM_CLENOW_PEAK_TRAIL_DROP:
            return True, (f"고점트레일 ({peak_gain*100:+.1f}% 고점 → "
                          f"{drop_from_peak*100:+.1f}% 풀백)")

    # 3) 일중 급락 — 30분 내 -4% 이상 하락
    if len(st["price_history"]) >= 2:
        recent_high = max(p for _, p in st["price_history"])
        rapid_drop = (current_price - recent_high) / recent_high
        if rapid_drop <= -DOM_CLENOW_FLASH_DROP_PCT:
            return True, (f"급락감지 ({DOM_CLENOW_FLASH_DROP_MIN}분내 "
                          f"{rapid_drop*100:+.2f}%)")

    return False, ""


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

        # v6.29: CLENOW 모드 3중 보호 (하드 SL -5% / 고점 트레일 / 일중 급락)
        if pos.get("strategy_type") == "CLENOW":
            should_exit, reason = _check_clenow_protections(
                ticker, pos, current_price)
            if should_exit:
                if trader.sell_market(
                    ticker, pos["name"], pos["qty"], pos["buy_price"], reason
                ):
                    closed.append(ticker)
                    unregister(ticker)
            continue  # CLENOW: 3중 보호 외에는 EOD MA50 만

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

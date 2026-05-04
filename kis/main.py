"""KIS 자동매매 봇 v3.0 — 섹터 모멘텀 스윙"""
import time
from datetime import datetime
import pytz
import scanner, scanner_overseas
import trader, trader_overseas
import monitor, monitor_overseas
import telegram
import kis_auth as api
from market_calendar import is_trading_day
from config import (
    DOM_SCAN_START, DOM_SCAN_END, DOM_EOD_CHECK, DOM_CLOSING_MSG,
    DOM_MAX_POSITIONS,
    OS_SCAN_TIME_START, OS_SCAN_TIME_END, OS_EOD_CHECK, OS_MAX_POSITIONS,
    SCAN_INTERVAL_SEC, MONITOR_INTERVAL_SEC, SUMMARY_INTERVAL_SEC,
    ACCOUNT_NO, IS_PAPER,
    DAILY_LOSS_CIRCUIT,
    DOM_STRATEGY_MODE, OS_STRATEGY_MODE,
    OS_LEVERAGED_BENCHMARK, OS_LEVERAGED_BULL, OS_LEVERAGED_BEAR,
    OS_LEVERAGED_SIGNAL_MA, OS_LEVERAGED_AUX_MA,
    OS_LEVERAGED_ALLOCATIONS,
    CLENOW_MAX_POSITIONS, CLENOW_EXIT_MA,
    DOM_SMALL_SEED_MODE, DOM_SMALL_SEED_MAX_PRICE, DOM_SMALL_SEED_POSITIONS,
    OS_SMALL_SEED_MODE, OS_SMALL_SEED_TICKER, OS_SMALL_SEED_BENCHMARK,
    OS_SMALL_SEED_ALLOCATIONS,
)

KST = pytz.timezone("Asia/Seoul")


def now_kst():
    return datetime.now(KST)


def hhmm():
    return now_kst().strftime("%H:%M")


# ═══════════════════════════════════════════════════════
# 시간대 헬퍼
# ═══════════════════════════════════════════════════════
def is_dom_market_hours() -> bool:
    """국내 장중(09:00~15:30, 영업일)"""
    if not is_trading_day(now_kst()):
        return False
    return "09:00" <= hhmm() <= "15:30"


def is_dom_scan_time() -> bool:
    if not is_trading_day(now_kst()):
        return False
    return DOM_SCAN_START <= hhmm() <= DOM_SCAN_END


def is_dom_eod_check() -> bool:
    """EOD 체크 윈도우: 15:15~15:20"""
    if not is_trading_day(now_kst()):
        return False
    t = hhmm()
    return DOM_EOD_CHECK <= t <= "15:20"


def is_os_market_hours() -> bool:
    """미장 시간대 (KST 22:30~06:00, 간단 고정)"""
    t = hhmm()
    return t >= "22:30" or t <= "06:00"


def is_os_scan_time() -> bool:
    t = hhmm()
    return OS_SCAN_TIME_START <= t <= OS_SCAN_TIME_END


def is_os_eod_check() -> bool:
    t = hhmm()
    return OS_EOD_CHECK <= t <= "05:55"


# ═══════════════════════════════════════════════════════
# 잔고 조회
# ═══════════════════════════════════════════════════════
def get_balance_info() -> dict:
    try:
        parts = ACCOUNT_NO.split("-")
        acc_no = parts[0]
        acc_prod = parts[1] if len(parts) > 1 else "01"
        tr_id = "VTTC8434R" if IS_PAPER else "TTTC8434R"
        data = api.get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id,
            {
                "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02",
                "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
            },
        )
        if data.get("rt_cd") == "0":
            o = data.get("output2", [{}])[0]
            return {
                "total_eval": int(o.get("tot_evlu_amt", 0)),
                "available": int(o.get("prvs_rcdl_excc_amt", 0)),
                "buy_amount": int(o.get("pchs_amt_smtl_amt", 0)),
                "eval_profit": int(o.get("evlu_pfls_smtl_amt", 0)),
                "profit_rate": float(o.get("asst_icdc_erng_rt", 0)),
            }
    except Exception as e:
        print(f"[BALANCE] 오류: {e}")
    return {}


# ═══════════════════════════════════════════════════════
# 현황 요약
# ═══════════════════════════════════════════════════════
def send_summary(dom_pos, os_pos, trade_count):
    lines = [f"📊 <b>현황 요약</b> ({hhmm()} KST)"]
    bal = get_balance_info()
    if bal:
        em = "📈" if bal["eval_profit"] >= 0 else "📉"
        lines.append(
            f"\n💰 <b>계좌</b>\n"
            f"총평가: {bal['total_eval']:,}원\n"
            f"주문가능: {bal['available']:,}원\n"
            f"{em} 평가손익: {bal['eval_profit']:+,}원 ({bal['profit_rate']:+.2f}%)"
        )
    if dom_pos:
        lines.append("\n🇰🇷 <b>국내 보유</b>")
        for t, p in dom_pos.items():
            lines.append(f"• {p['name']}({t}) {p['qty']}주 @ {p['buy_price']:,}")
    else:
        lines.append("\n🇰🇷 국내 보유 없음")
    if os_pos:
        lines.append("\n🇺🇸 <b>해외 보유</b>")
        for t, p in os_pos.items():
            lines.append(f"• {p['name']}({t}) {p['qty']}주 @ ${p['buy_price']:.2f}")
    else:
        lines.append("\n🇺🇸 해외 보유 없음")
    lines.append(f"\n📈 오늘 거래: {trade_count}회")
    telegram.send("\n".join(lines), dedup_sec=600)


# ═══════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════
def main():
    print("=" * 55)
    print("🚀 KIS 자동매매 봇 v3.2")
    print(f"국내 전략: {DOM_STRATEGY_MODE} | 해외 전략: {OS_STRATEGY_MODE}")
    print(f"국내 진입: {DOM_SCAN_START}~{DOM_SCAN_END} | EOD체크 {DOM_EOD_CHECK}")
    print(f"해외 진입: {OS_SCAN_TIME_START}~{OS_SCAN_TIME_END} (KST)")
    print(f"현재: {hhmm()} KST")
    print("=" * 55)

    try:
        api.get_access_token()
    except Exception as e:
        print(f"[AUTH] 초기 토큰 실패: {e}")
    time.sleep(2)

    # 전략 모드별 메시지 구성
    if DOM_STRATEGY_MODE == "clenow":
        dom_max = DOM_SMALL_SEED_POSITIONS if DOM_SMALL_SEED_MODE else CLENOW_MAX_POSITIONS
        dom_desc = (f"국내: <b>Clenow 모멘텀</b> ({dom_max}포지션, "
                    f"단가≤₩{DOM_SMALL_SEED_MAX_PRICE:,})"
                    if DOM_SMALL_SEED_MODE else
                    f"국내: <b>Clenow 모멘텀</b> ({dom_max}포지션 분산)")
    else:
        dom_desc = f"국내: 섹터 스윙 (최대 {DOM_MAX_POSITIONS}포지션)"

    if OS_STRATEGY_MODE == "leveraged":
        if OS_SMALL_SEED_MODE:
            etf_list = ", ".join(a["ticker"] for a in OS_SMALL_SEED_ALLOCATIONS)
            os_desc = f"해외: <b>레버리지 체제</b> ({etf_list} 분산, MA200)"
        else:
            etf_list = ", ".join(a["ticker"] for a in OS_LEVERAGED_ALLOCATIONS)
            os_desc = f"해외: <b>레버리지 4-way</b> ({etf_list}, MA200)"
    else:
        os_desc = f"해외: 섹터 스윙 (최대 {OS_MAX_POSITIONS}포지션)"

    paper_label = "📝 모의투자" if IS_PAPER else "💵 실거래"

    telegram.send_force(
        "🚀 <b>KIS 봇 v3.2 시작</b>\n"
        f"{paper_label}\n"
        f"{dom_desc}\n"
        f"{os_desc}\n"
        f"국내 진입창: {DOM_SCAN_START}~{DOM_SCAN_END}\n"
        f"해외 진입창: {OS_SCAN_TIME_START}~{OS_SCAN_TIME_END} KST\n"
        f"현재 {hhmm()} KST"
    )

    dom_pos, os_pos = {}, {}
    last_dom_scan = last_os_scan = None
    last_dom_mon = last_os_mon = None
    last_summary = None
    dom_eod_done = False
    os_eod_done = False
    sent_closing = False
    trade_count = 0
    # 서킷 브레이커 상태
    circuit_tripped = False  # 당일 재진입 중단 플래그
    day_start_eval = None    # 장 시작 시 총평가 (손실률 계산 기준)

    def elapsed(t):
        return 9999 if t is None else (now_kst() - t).seconds

    while True:
        now = now_kst()
        t_hm = now.strftime("%H:%M")

        # ════ 국내장 ════════════════════════════════════
        if is_dom_market_hours():
            # 09:00 ~ 09:05 초기화
            if t_hm == "09:00":
                dom_eod_done = False
                sent_closing = False
                circuit_tripped = False
                bal0 = get_balance_info()
                day_start_eval = bal0.get("total_eval", 0) if bal0 else 0

            # 일일 손실 서킷 브레이커
            if not circuit_tripped and day_start_eval and day_start_eval > 0:
                bal_now = get_balance_info()
                if bal_now:
                    loss_pct = (bal_now["total_eval"] - day_start_eval) / day_start_eval
                    if loss_pct <= -DAILY_LOSS_CIRCUIT:
                        circuit_tripped = True
                        telegram.send_force(
                            f"🛑 <b>일일 손실 서킷 발동</b>\n"
                            f"손실 {loss_pct*100:+.2f}% ≤ -{DAILY_LOSS_CIRCUIT*100:.0f}%\n"
                            "당일 신규 진입 중단"
                        )

            # 보유 포지션 실시간 감시
            if dom_pos and elapsed(last_dom_mon) >= MONITOR_INTERVAL_SEC:
                closed = monitor.check_positions(dom_pos)
                for t in closed:
                    dom_pos.pop(t, None)
                    trade_count += 1
                last_dom_mon = now

            # 신규 진입 (스캔 시간대) — 서킷 발동 시 skip
            if DOM_STRATEGY_MODE == "clenow":
                max_pos = (DOM_SMALL_SEED_POSITIONS if DOM_SMALL_SEED_MODE
                           else CLENOW_MAX_POSITIONS)
            else:
                max_pos = DOM_MAX_POSITIONS
            if (is_dom_scan_time() and not circuit_tripped
                    and len(dom_pos) < max_pos):
                if elapsed(last_dom_scan) >= SCAN_INTERVAL_SEC:
                    try:
                        if DOM_STRATEGY_MODE == "clenow":
                            import strategy_clenow_kr as clenow
                            # 자동 가격상한: 시드 작으면 (총자본 95% / 포지션수) 까지 = 1주 보장
                            if DOM_SMALL_SEED_MODE:
                                bal_chk = get_balance_info()
                                total_eval = bal_chk.get("total_eval", 0) if bal_chk else 0
                                # 총자본 / 포지션수 (95% 비중) — env 의 MAX_PRICE 와 비교해 큰 쪽
                                auto_cap = int(total_eval * 0.95 / max(max_pos, 1))
                                price_ceiling = max(auto_cap, DOM_SMALL_SEED_MAX_PRICE)
                            else:
                                price_ceiling = None
                            cands = clenow.scan_clenow_candidates(
                                excluded_tickers=list(dom_pos.keys()),
                                max_positions=max_pos - len(dom_pos),
                                max_price=price_ceiling,
                            )
                        else:
                            cands = scanner.scan_candidates(
                                exclude_tickers=list(dom_pos.keys())
                            )
                    except Exception as e:
                        print(f"[MAIN] 국내 스캔 오류: {e}")
                        cands = []
                    for c in cands:
                        if len(dom_pos) >= max_pos:
                            break
                        res = trader.buy_market(
                            c["ticker"], c["name"],
                            reason=c.get("reason", f"[{DOM_STRATEGY_MODE}] 진입"),
                            expected_price=c.get("close") or c.get("price"),
                        )
                        if res:
                            res["strategy_type"] = DOM_STRATEGY_MODE.upper()
                            dom_pos[c["ticker"]] = res
                            monitor.register_position(
                                c["ticker"], res["buy_price"], DOM_STRATEGY_MODE.upper()
                            )
                            trade_count += 1
                    last_dom_scan = now

            # EOD 일봉 청산 체크 (15:15 ~ 15:20, 1회만)
            if is_dom_eod_check() and not dom_eod_done and dom_pos:
                print("[MAIN] EOD 일봉 청산 체크")
                closed = monitor.check_eod(dom_pos)
                for t in closed:
                    dom_pos.pop(t, None)
                    trade_count += 1
                dom_eod_done = True

        # ════ 해외장 ════════════════════════════════════
        if is_os_market_hours():
            if t_hm == "22:30":
                os_eod_done = False

            # ─── Leveraged Regime 전략 ─────────────────
            if OS_STRATEGY_MODE == "leveraged":
                # 스캔 시간대에 1회만 체제 체크 (중복 실행 방지용 체제 플래그)
                if is_os_scan_time() and elapsed(last_os_scan) >= SCAN_INTERVAL_SEC:
                    try:
                        import strategy_leveraged
                        bal = trader_overseas.get_overseas_balance()
                        total_account = bal.get("available_usd", 0)
                        # 현재 보유 ETF 평가액 포함
                        for pos in os_pos.values():
                            total_account += pos["qty"] * pos["buy_price"]

                        # 소액 시드: OS_SMALL_SEED_TICKERS 파싱 (1~N개)
                        if OS_SMALL_SEED_MODE:
                            allocations = OS_SMALL_SEED_ALLOCATIONS
                        else:
                            allocations = OS_LEVERAGED_ALLOCATIONS

                        # 슬리브 1개 이상이면 split 함수로 일괄 처리
                        if len(allocations) >= 1:
                            result = strategy_leveraged.check_and_execute_split(
                                allocations=allocations,
                                current_positions=os_pos,
                                total_account_usd=total_account,
                                signal_ma=OS_LEVERAGED_SIGNAL_MA,
                                aux_ma=OS_LEVERAGED_AUX_MA,
                            )
                            trade_count += len(result.get("switches", []))
                        else:
                            # 단일 모드 (레거시)
                            curr = next(iter(os_pos.values())) if os_pos else None
                            cfg = {
                                "benchmark":  OS_LEVERAGED_BENCHMARK,
                                "bull_ticker": OS_LEVERAGED_BULL,
                                "bear_ticker": OS_LEVERAGED_BEAR,
                                "signal_ma":  OS_LEVERAGED_SIGNAL_MA,
                                "aux_ma":     OS_LEVERAGED_AUX_MA,
                            }
                            result = strategy_leveraged.check_and_execute(cfg, curr, total_account)
                            if result["action"] in ("switch", "buy_success"):
                                new_pos = result["new_position"]
                                if new_pos:
                                    os_pos = {new_pos["ticker"]: new_pos}
                                    trade_count += 1
                            elif result["action"] == "sell":
                                os_pos = {}
                                trade_count += 1
                    except Exception as e:
                        print(f"[MAIN] 해외 레버리지 체제 오류: {e}")
                    last_os_scan = now
            # ─── Swing 전략 (기존) ──────────────────────
            else:
                # 실시간 감시
                if os_pos and elapsed(last_os_mon) >= MONITOR_INTERVAL_SEC:
                    closed = monitor_overseas.check_overseas_positions(os_pos)
                    for t in closed:
                        os_pos.pop(t, None)
                        trade_count += 1
                    last_os_mon = now

                # 진입 스캔 (22:45 ~ 23:15)
                if is_os_scan_time() and len(os_pos) < OS_MAX_POSITIONS:
                    if elapsed(last_os_scan) >= SCAN_INTERVAL_SEC:
                        try:
                            cands = scanner_overseas.scan_overseas_candidates(
                                exclude_tickers=list(os_pos.keys())
                            )
                        except Exception as e:
                            print(f"[MAIN] 해외 스캔 오류: {e}")
                            cands = []
                        for c in cands:
                            if len(os_pos) >= OS_MAX_POSITIONS:
                                break
                            res = trader_overseas.buy_overseas(
                                c["ticker"], c["name"], c["exchange"],
                                reason=f"[{c.get('regime','')}] {c['reason']}",
                            )
                            if res:
                                os_pos[c["ticker"]] = res
                                trade_count += 1
                        last_os_scan = now

                # EOD (05:45 ~ 05:55)
                if is_os_eod_check() and not os_eod_done and os_pos:
                    print("[MAIN] 해외 EOD 체크")
                    closed = monitor_overseas.check_overseas_eod(os_pos)
                    for t in closed:
                        os_pos.pop(t, None)
                        trade_count += 1
                    os_eod_done = True

        # ════ 현황 요약 (1시간 주기) ═══════════════════
        if elapsed(last_summary) >= SUMMARY_INTERVAL_SEC:
            if is_dom_market_hours() or is_os_market_hours():
                send_summary(dom_pos, os_pos, trade_count)
            last_summary = now

        # ════ 일일 결산 (15:35) ════════════════════════
        if t_hm == DOM_CLOSING_MSG and not sent_closing and is_trading_day(now):
            bal = get_balance_info()
            msg = f"📋 <b>오늘 결산</b>\n거래: {trade_count}회"
            if bal:
                em = "📈" if bal["eval_profit"] >= 0 else "📉"
                msg += (
                    f"\n총평가: {bal['total_eval']:,}원\n"
                    f"{em} 손익: {bal['eval_profit']:+,}원 ({bal['profit_rate']:+.2f}%)"
                )
            if dom_pos:
                msg += "\n\n🇰🇷 보유 유지:"
                for t, p in dom_pos.items():
                    msg += f"\n• {p['name']}({t})"
            telegram.send_force(msg)
            sent_closing = True
            trade_count = 0

        time.sleep(5)


if __name__ == "__main__":
    main()

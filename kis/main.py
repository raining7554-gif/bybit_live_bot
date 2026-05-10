"""KIS 자동매매 봇 v3.0 — 섹터 모멘텀 스윙"""
import os
import time
from datetime import datetime
import pytz
import scanner, scanner_overseas
import trader, trader_overseas
import monitor, monitor_overseas
import telegram
import kis_auth as api
from market_calendar import is_trading_day

# 공유 학습 모듈 (kis/intelligence/ 복사본). 실패해도 봇은 정상 동작.
try:
    from intelligence import journal as _journal, agent as _agent
except Exception as _e:
    _journal = _agent = None
    print(f"[MAIN] intelligence 모듈 로드 실패: {_e}")
from config import (
    DOM_SCAN_START, DOM_SCAN_END, DOM_EOD_CHECK, DOM_CLOSING_MSG,
    DOM_MAX_POSITIONS,
    OS_SCAN_TIME_START, OS_SCAN_TIME_END, OS_EOD_CHECK, OS_MAX_POSITIONS,
    SCAN_INTERVAL_SEC, MONITOR_INTERVAL_SEC, SUMMARY_INTERVAL_SEC,
    ACCOUNT_NO, IS_PAPER,
    DAILY_LOSS_CIRCUIT, TOTAL_DAILY_LOSS_CIRCUIT,
    DOM_STRATEGY_MODE, OS_STRATEGY_MODE,
    OS_LEVERAGED_BENCHMARK, OS_LEVERAGED_BULL, OS_LEVERAGED_BEAR,
    OS_LEVERAGED_SIGNAL_MA, OS_LEVERAGED_AUX_MA,
    OS_LEVERAGED_ALLOCATIONS,
    CLENOW_MAX_POSITIONS, CLENOW_EXIT_MA,
    CLENOW_WINDOW, CLENOW_TOP_PCT,
    ROTATION_ALERT_ONLY, ROTATION_SCORE_GAP_MIN, ROTATION_MIN_HOLD_DAYS,
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


def _in_window(t: str, start: str, end: str) -> bool:
    """KST 시간 윈도우 체크. start > end 이면 자정 넘어가는 윈도우로 판정.

    예) start='22:30', end='05:30' → 22:30~23:59 또는 00:00~05:30 = True
    """
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def is_os_scan_time() -> bool:
    """v3.3: 자정 넘어가는 진입창 지원."""
    return _in_window(hhmm(), OS_SCAN_TIME_START, OS_SCAN_TIME_END)


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
        rt_cd = data.get("rt_cd")
        if rt_cd == "0":
            o = data.get("output2", [{}])[0]
            total_eval = int(float(o.get("tot_evlu_amt", 0) or 0))
            eval_profit = int(float(o.get("evlu_pfls_smtl_amt", 0) or 0))
            buy_amount = int(float(o.get("pchs_amt_smtl_amt", 0) or 0))
            # v6.6: 가용금액 — KIS 가 여러 필드로 줘서 가장 큰 값 사용
            # nxdy_excc_amt (익일정산), prvs_rcdl_excc_amt (가수도), dnca_tot_amt (예수금)
            avail_candidates = [
                int(float(o.get("nxdy_excc_amt", 0) or 0)),
                int(float(o.get("prvs_rcdl_excc_amt", 0) or 0)),
                int(float(o.get("dnca_tot_amt", 0) or 0)),
            ]
            available = max(avail_candidates)
            # v6.6: 수익률 — KIS asst_icdc_erng_rt 가 0 으로 자주 옴 → 직접 계산
            kis_rate = float(o.get("asst_icdc_erng_rt", 0) or 0)
            if kis_rate == 0 and buy_amount > 0:
                profit_rate = (eval_profit / buy_amount) * 100
            else:
                profit_rate = kis_rate
            return {
                "total_eval": total_eval,
                "available": available,
                "buy_amount": buy_amount,
                "eval_profit": eval_profit,
                "profit_rate": profit_rate,
            }
        # v3.6: 잔고 0 진단용 — 응답 본체를 로그에 남김
        msg1 = data.get("msg1", "")
        msg_cd = data.get("msg_cd", "")
        print(f"[BALANCE] 잔고 조회 실패 rt_cd={rt_cd} msg_cd={msg_cd} "
              f"msg={msg1[:200]}")
        print(f"[BALANCE] CANO={acc_no} ACNT_PRDT_CD={acc_prod} "
              f"TR_ID={tr_id} IS_PAPER={IS_PAPER}")
    except Exception as e:
        print(f"[BALANCE] 오류: {e}")
    return {}


# ═══════════════════════════════════════════════════════
# v6.4: 시작 시 기존 보유 종목 동기화
# ═══════════════════════════════════════════════════════
def load_kr_holdings() -> dict:
    """KIS inquire-balance output1 → dom_pos dict.

    이전엔 봇 재시작시 dom_pos = {} 빈 채로 시작 → 기존 보유 인식 못함.
    이 함수가 broker 의 실제 보유를 봇 메모리에 동기화.
    """
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
        if data.get("rt_cd") != "0":
            print(f"[SYNC_KR] 잔고 조회 실패: {data.get('msg1', '')}")
            return {}
        holdings = {}
        for item in data.get("output1", []):
            qty = int(item.get("hldg_qty", 0) or 0)
            if qty <= 0:
                continue
            ticker = item.get("pdno", "").strip()
            name = item.get("prdt_name", ticker).strip()
            avg_price = int(float(item.get("pchs_avg_pric", 0) or 0))
            if not ticker or avg_price <= 0:
                continue
            holdings[ticker] = {
                "ticker": ticker, "name": name,
                "qty": qty, "buy_price": avg_price,
                "strategy_type": DOM_STRATEGY_MODE.upper(),
                # buy_date 없음 — rotation min_hold_days 가 None 처리하도록
            }
        return holdings
    except Exception as e:
        print(f"[SYNC_KR] 예외: {e}")
        return {}


def load_us_holdings() -> dict:
    """KIS overseas inquire-present-balance → os_pos dict."""
    try:
        parts = ACCOUNT_NO.split("-")
        acc_no = parts[0]
        acc_prod = parts[1] if len(parts) > 1 else "01"
        tr_id = "VTRP6504R" if IS_PAPER else "CTRP6504R"
        data = api.get(
            "/uapi/overseas-stock/v1/trading/inquire-present-balance",
            tr_id,
            {
                "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
                "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
            },
        )
        if data.get("rt_cd") != "0":
            print(f"[SYNC_US] 잔고 조회 실패: {data.get('msg1', '')}")
            return {}
        holdings = {}
        for item in data.get("output1", []):
            qty = float(item.get("ovrs_cblc_qty", 0) or 0)
            if qty <= 0:
                continue
            ticker = item.get("pdno", "").strip()
            name = item.get("prdt_name", ticker).strip() or ticker
            avg_price = float(item.get("pchs_avg_pric", 0) or 0)
            exchange = (item.get("ovrs_excg_cd", "") or "NAS").strip()
            if not ticker or avg_price <= 0:
                continue
            # KIS 의 거래소 코드 → 우리 코드 매핑
            exch_map = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}
            exchange = exch_map.get(exchange, exchange)
            holdings[ticker] = {
                "ticker": ticker, "name": name, "exchange": exchange,
                "qty": qty, "buy_price": avg_price,
                "market": "overseas",
            }
        return holdings
    except Exception as e:
        print(f"[SYNC_US] 예외: {e}")
        return {}


def sync_holdings_at_startup() -> tuple[dict, dict]:
    """봇 시작/재시작 시 broker 실제 보유 → dom_pos / os_pos 복원."""
    dom = load_kr_holdings()
    us = load_us_holdings()
    if dom:
        print(f"[SYNC] KR 보유 {len(dom)}종 복원: {', '.join(dom.keys())}")
    if us:
        print(f"[SYNC] US 보유 {len(us)}종 복원: {', '.join(us.keys())}")
    return dom, us


# ═══════════════════════════════════════════════════════
# 현황 요약
# ═══════════════════════════════════════════════════════
def send_summary(dom_pos, os_pos, trade_count):
    """정각 KST 리포트 — 시장 운영시간 내에 1시간마다.

    국내장 (09:00~15:30) 또는 미장 (22:30~05:30) 동안 정각에 호출.
    잔고 (KRW + USD), 보유종목 + 실시간 PnL, 오늘 거래수 표시.
    """
    bal = get_balance_info()

    # USD 가용 잔고
    try:
        import trader_overseas as _ot
        os_bal = _ot.get_overseas_balance()
        usd_avail = os_bal.get("available_usd", 0)
    except Exception:
        usd_avail = 0

    lines = [f"⏰ <b>{hhmm()} KST</b>"]

    if bal:
        em = "📈" if bal.get("eval_profit", 0) >= 0 else "📉"
        lines.append(
            f"💰 KRW ₩{bal.get('total_eval', 0):,} (가용 ₩{bal.get('available', 0):,})\n"
            f"   USD 가용 ${usd_avail:.2f}\n"
            f"   {em} 손익 ₩{bal.get('eval_profit', 0):+,} "
            f"({bal.get('profit_rate', 0):+.2f}%)"
        )

    # 국내 보유 + 현재가 + PnL
    if dom_pos:
        lines.append("\n🇰🇷 <b>국내</b>")
        for t, p in dom_pos.items():
            buy = p.get('buy_price', 0)
            qty = p.get('qty', 0)
            cur = buy
            try:
                d = api.get(
                    "/uapi/domestic-stock/v1/quotations/inquire-price",
                    "FHKST01010100",
                    {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": t},
                )
                cur = int(d.get("output", {}).get("stck_prpr", buy)) or buy
            except Exception:
                pass
            pnl_pct = (cur - buy) / buy * 100 if buy else 0
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            lines.append(
                f"  {pnl_emoji} {p.get('name', t)}({t}) {qty}주 "
                f"@ ₩{buy:,} → ₩{cur:,} ({pnl_pct:+.2f}%)"
            )

    # 해외 보유 + 현재가 + PnL
    if os_pos:
        lines.append("\n🇺🇸 <b>해외</b>")
        for t, p in os_pos.items():
            buy = p.get('buy_price', 0)
            qty = p.get('qty', 0)
            cur = buy
            exc = p.get('exchange', 'NAS')
            try:
                d = api.get(
                    "/uapi/overseas-price/v1/quotations/price",
                    "HHDFS00000300",
                    {"AUTH": "", "EXCD": exc, "SYMB": t},
                )
                out = d.get("output", {})
                # last 가 비어있으면 base 로 fallback
                for k in ("last", "base", "open"):
                    v = out.get(k)
                    if v not in (None, "", "0"):
                        try:
                            fv = float(v)
                            if fv > 0:
                                cur = fv
                                break
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass
            pnl_pct = (cur - buy) / buy * 100 if buy else 0
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            lines.append(
                f"  {pnl_emoji} {p.get('name', t)}({t}) {qty}주 "
                f"@ ${buy:.2f} → ${cur:.2f} ({pnl_pct:+.2f}%)"
            )

    if not dom_pos and not os_pos:
        lines.append("\n포지션: 없음")

    lines.append(f"\n📊 오늘 거래: {trade_count}회")
    telegram.send_force("\n".join(lines))


# ═══════════════════════════════════════════════════════
# 데이터 자가진단 (시작시 1회)
# ═══════════════════════════════════════════════════════
def _data_health_check() -> dict:
    """KIS 일봉 API + 잔고가 거래 가능 상태인지 검증.

    검증 항목:
      - DOM_STRATEGY_MODE=clenow → KOSPI 220일
      - OS_STRATEGY_MODE=leveraged → 각 ETF 슬리브 벤치마크
      - 항상 → KRW + USD 잔고 (환전 여부 확인)

    리턴: {symbol|tag: int(일수)|str(에러)|str("$X.XX") }
    """
    results: dict = {}

    if DOM_STRATEGY_MODE == "clenow":
        try:
            from strategy_clenow_kr import get_kr_daily
            kospi = get_kr_daily("069500", count=220, market_code="J")
            if len(kospi) < 200:
                kospi = get_kr_daily("005930", count=220, market_code="J")
            results["KOSPI(proxy)"] = len(kospi)
        except Exception as e:
            results["KOSPI(proxy)"] = f"ERR: {type(e).__name__}: {str(e)[:80]}"

    if OS_STRATEGY_MODE == "leveraged":
        try:
            from strategy_leveraged import get_overseas_daily
            allocations = (OS_SMALL_SEED_ALLOCATIONS if OS_SMALL_SEED_MODE
                           else OS_LEVERAGED_ALLOCATIONS)
            checked: set = set()
            for alloc in allocations:
                bench = alloc.get("benchmark", "SPY")
                if bench in checked:
                    continue
                checked.add(bench)
                exc = "NAS" if bench == "QQQ" else "AMS"
                data = get_overseas_daily(bench, exchange=exc, count=220)
                results[bench] = len(data)
        except Exception as e:
            results["US_BENCH"] = f"ERR: {type(e).__name__}: {str(e)[:80]}"

    # v3.5: 잔고 검증 — 환전 여부 확인용
    try:
        krw_bal = get_balance_info()
        krw = krw_bal.get("total_eval", 0) if krw_bal else 0
        results["KRW"] = f"₩{krw:,}"
    except Exception as e:
        results["KRW"] = f"ERR: {type(e).__name__}"
    try:
        import trader_overseas as _ot
        os_bal = _ot.get_overseas_balance()
        avail = os_bal.get("available_usd", 0)
        total = os_bal.get("total_eval_usd", 0)
        results["USD가용"] = f"${avail:.2f}"
        if avail < 50 and total > 0:
            results["USD가용"] += " ⚠️환전필요"
    except Exception as e:
        results["USD가용"] = f"ERR: {type(e).__name__}"

    return results


def _format_health_report(results: dict) -> str:
    """텔레그램용 자가진단 결과 포매팅."""
    if not results:
        return ""
    lines = ["🔍 <b>데이터 자가진단</b>"]
    all_ok = True
    for k, v in results.items():
        if isinstance(v, int):
            ok = v >= 200
            icon = "✅" if ok else ("⚠️" if v >= 100 else "❌")
            lines.append(f"  {k}: {v}일 {icon}")
            if not ok:
                all_ok = False
        elif isinstance(v, str) and v.startswith("ERR"):
            lines.append(f"  {k}: ❌ {v}")
            all_ok = False
        else:
            # KRW / USD 같은 표시값
            lines.append(f"  {k}: {v}")
    if all_ok:
        lines.append("→ 모든 데이터 정상")
    else:
        lines.append("→ ⚠️ 일부 데이터 부족 — 진입 안될 수 있음")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# v4.0: 통합 잔고 (KRW+USD 환산)
# ═══════════════════════════════════════════════════════
def get_total_equity_krw() -> int:
    """KRW + USD (환산) 합계 잔고 — 통합 서킷 브레이커용."""
    krw = 0
    try:
        bal = get_balance_info()
        if bal:
            krw = bal.get("total_eval", 0)
    except Exception:
        pass
    usd_krw = 0
    try:
        import trader_overseas as _ot
        os_bal = _ot.get_overseas_balance()
        usd_avail = os_bal.get("available_usd", 0)
        # 대략 환율 1450 (정확하지 않아도 됨, 비율만 보면 OK)
        usd_krw = int(usd_avail * 1450)
    except Exception:
        pass
    return krw + usd_krw


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
        # v6.2: budget + 소수점 표기
        try:
            from config import US_FRACTIONAL_ENABLED, OS_POSITION_USD as _opu
        except ImportError:
            US_FRACTIONAL_ENABLED, _opu = False, 600
        frac = " 🔢소수점" if US_FRACTIONAL_ENABLED else ""
        os_desc = (
            f"해외: 섹터 스윙 (최대 {OS_MAX_POSITIONS}포지션, "
            f"종목당 ${_opu:.0f}{frac})"
        )

    paper_label = "📝 모의투자" if IS_PAPER else "💵 실거래"

    # 데이터 자가진단 — 진입창 기다릴 필요 없이 즉시 API 정상 여부 확인
    health = _data_health_check()
    health_report = _format_health_report(health)

    ai_label = ("🧠 AI: ON" if (_agent is not None and _agent._enabled())
                else "🧠 AI: OFF")
    telegram.send_force(
        "🚀 <b>KIS 봇 v3.2 시작</b>\n"
        f"{paper_label}\n"
        f"{dom_desc}\n"
        f"{os_desc}\n"
        f"국내 진입창: {DOM_SCAN_START}~{DOM_SCAN_END}\n"
        f"해외 진입창: {OS_SCAN_TIME_START}~{OS_SCAN_TIME_END} KST\n"
        f"현재 {hhmm()} KST\n"
        f"{ai_label} | 명령: /review /lessons /propose /symbols /diagnose /news /scan_us\n"
        f"⏰ 운영시간 정각마다 현황 리포트"
        + (f"\n\n{health_report}" if health_report else "")
    )

    dom_pos, os_pos = sync_holdings_at_startup()
    if dom_pos or os_pos:
        try:
            lines = ["♻️ <b>기존 보유 동기화</b>"]
            for t, p in dom_pos.items():
                lines.append(f"   🇰🇷 {p['name']}({t}) {p['qty']}주 @ ₩{p['buy_price']:,}")
            for t, p in os_pos.items():
                qd = (f"{p['qty']:.4f}" if isinstance(p['qty'], float) and p['qty'] != int(p['qty'])
                      else f"{int(p['qty'])}")
                lines.append(f"   🇺🇸 {p['name']}({t}) {qd}주 @ ${p['buy_price']:.2f}")
            telegram.send_force("\n".join(lines))
        except Exception as e:
            print(f"[SYNC] 텔레그램 알림 실패: {e}")
    last_dom_scan = last_os_scan = None
    last_dom_mon = last_os_mon = None
    # v4.0: 통합 서킷 브레이커 상태
    total_circuit_tripped = False
    total_day_anchor_krw = 0  # 시작 시점 KRW+USD 합계 (KRW 환산)
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

    # ════ 텔레그램 명령 핸들러 ═══════════════════════════════════
    def _all_kis_bot_ids() -> list:
        return [f"kis_kr_{DOM_STRATEGY_MODE}", f"kis_us_{OS_STRATEGY_MODE}"]

    def cmd_review():
        if _agent is None:
            telegram.send("intelligence 모듈 미로드 — /review 사용 불가")
            return
        telegram.send("📊 KIS 주간 회고 분석 중...")
        # 국내 + 미국 두 봇 각각 회고 (현재는 같은 SQLite, 봇별 분리)
        for bid in _all_kis_bot_ids():
            _agent.weekly_review_async(
                bot_id=bid, send_telegram=lambda m: telegram.send(m, dedup_sec=60),
                verbose_errors=True,
            )

    def cmd_lessons():
        if _journal is None:
            telegram.send("intelligence 모듈 미로드")
            return
        for bid in _all_kis_bot_ids():
            rows = _journal.recent_lessons(bot_id=bid, limit=5)
            if not rows:
                telegram.send(f"📚 {bid}: 누적 교훈 없음", dedup_sec=60)
                continue
            lines = [f"📚 <b>{bid} 교훈</b>"]
            for i, r in enumerate(rows, 1):
                lines.append(f"{i}. {r.get('lesson', '?')}")
            telegram.send("\n".join(lines), dedup_sec=60)

    def cmd_propose():
        if _agent is None:
            telegram.send("intelligence 모듈 미로드")
            return
        telegram.send("⚙️ KIS 파라미터 제안 분석 중...")
        # 현재 활성 파라미터 (일부만 노출)
        from config import (
            DOM_SMALL_SEED_MAX_PRICE, DOM_SMALL_SEED_POSITIONS,
            OS_LEVERAGED_SIGNAL_MA, OS_LEVERAGED_AUX_MA,
            DAILY_LOSS_CIRCUIT, CLENOW_EXIT_MA,
        )
        kr_params = {
            "DOM_SMALL_SEED_MAX_PRICE": DOM_SMALL_SEED_MAX_PRICE,
            "DOM_SMALL_SEED_POSITIONS": DOM_SMALL_SEED_POSITIONS,
            "CLENOW_EXIT_MA": CLENOW_EXIT_MA,
            "DAILY_LOSS_CIRCUIT": DAILY_LOSS_CIRCUIT,
        }
        us_params = {
            "OS_LEVERAGED_SIGNAL_MA": OS_LEVERAGED_SIGNAL_MA,
            "OS_LEVERAGED_AUX_MA": OS_LEVERAGED_AUX_MA,
            "DAILY_LOSS_CIRCUIT": DAILY_LOSS_CIRCUIT,
        }
        _agent.propose_async(
            bot_id=f"kis_kr_{DOM_STRATEGY_MODE}",
            current_params=kr_params,
            send_telegram=lambda m: telegram.send(m, dedup_sec=60),
            verbose_errors=True,
        )
        _agent.propose_async(
            bot_id=f"kis_us_{OS_STRATEGY_MODE}",
            current_params=us_params,
            send_telegram=lambda m: telegram.send(m, dedup_sec=60),
            verbose_errors=True,
        )

    def cmd_symbols():
        if _journal is None:
            telegram.send("intelligence 모듈 미로드")
            return
        # 7일 + 30일 두 윈도우로 봇별 출력
        for days in (7, 30):
            for bid in _all_kis_bot_ids():
                msg = _journal.format_symbol_stats(
                    bot_id=bid, since_seconds=days * 86400,
                )
                telegram.send(msg, dedup_sec=60)

    def cmd_balance():
        """잔고 조회 진단 — 실패시 정확한 KIS API 응답 메시지 표시."""
        def _sf(v, default=0.0):
            if v is None or v == "":
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        parts = ACCOUNT_NO.split("-")
        acc_no = parts[0] if parts else ""
        acc_prod = parts[1] if len(parts) > 1 else "01"
        masked = (acc_no[:3] + "***" + acc_no[-2:]) if len(acc_no) >= 5 else "?"

        lines = [
            "🔍 <b>잔고 진단</b>",
            f"계좌: {masked}-{acc_prod}",
            f"IS_PAPER: {IS_PAPER}",
            f"len(CANO)={len(acc_no)} parts={len(parts)}",
            "─────────",
        ]

        # 1) 국내 잔고
        try:
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
            rt_cd = data.get("rt_cd", "?")
            msg1 = data.get("msg1", "")[:120]
            msg_cd = data.get("msg_cd", "")
            if rt_cd == "0":
                o = data.get("output2", [{}])[0]
                lines.append(f"✅ 국내 ({tr_id})")
                lines.append(f"  총평가: ₩{int(o.get('tot_evlu_amt', 0)):,}")
                lines.append(f"  주문가능: ₩{int(o.get('prvs_rcdl_excc_amt', 0)):,}")
            else:
                lines.append(f"❌ 국내 ({tr_id})")
                lines.append(f"  rt_cd={rt_cd} msg_cd={msg_cd}")
                lines.append(f"  msg: {msg1}")
        except Exception as e:
            lines.append(f"❌ 국내 EXC: {type(e).__name__}: {str(e)[:100]}")

        # 2) 해외 잔고 (CTRP6504R)
        try:
            tr_id = "VTRP6504R" if IS_PAPER else "CTRP6504R"
            data = api.get(
                "/uapi/overseas-stock/v1/trading/inquire-present-balance",
                tr_id,
                {
                    "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                    "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
                    "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
                },
            )
            rt_cd = data.get("rt_cd", "?")
            msg1 = data.get("msg1", "")[:120]
            if rt_cd == "0":
                o3 = data.get("output3", {})
                o2_list = data.get("output2", []) or []
                lines.append(f"✅ 해외종합 ({tr_id})")
                lines.append(f"  총자산: ${_sf(o3.get('tot_asst_amt')):.2f}")
                lines.append(f"  외화예치1: ${_sf(o3.get('frcr_dncl_amt1')):.2f}")
                lines.append(f"  외화예치2: ${_sf(o3.get('frcr_dncl_amt')):.2f}")
                # v3.7: output2 통화별 목록 표시
                if o2_list:
                    lines.append(f"  output2 ({len(o2_list)} 통화):")
                    for entry in o2_list[:5]:
                        if not isinstance(entry, dict):
                            continue
                        crcy = entry.get("crcy_cd", "?")
                        amts = []
                        for k in ("frcr_dncl_amt1", "frcr_dncl_amt",
                                  "ord_psbl_frcr_amt", "frcr_evlu_amt"):
                            v = _sf(entry.get(k))
                            if v > 0:
                                amts.append(f"{k}={v:.2f}")
                        line = f"    {crcy}: " + (", ".join(amts) if amts else "(0)")
                        lines.append(line[:100])
                else:
                    lines.append(f"  output2: (없음)")
            else:
                lines.append(f"❌ 해외종합 ({tr_id})")
                lines.append(f"  rt_cd={rt_cd} msg: {msg1}")
        except Exception as e:
            lines.append(f"❌ 해외종합 EXC: {type(e).__name__}: {str(e)[:100]}")

        # 3) 해외 매수가능 (JTTT3007R) — 더미 종목 코드로 호출
        try:
            tr_id = "VTTT3007R" if IS_PAPER else "JTTT3007R"
            data = api.get(
                "/uapi/overseas-stock/v1/trading/inquire-psamount",
                tr_id,
                {
                    "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                    "OVRS_EXCG_CD": "NASD", "OVRS_ORD_UNPR": "100",
                    "ITEM_CD": "AAPL",  # v3.8: 더미 종목 (KIS가 종목코드 요구)
                },
            )
            rt_cd = data.get("rt_cd", "?")
            msg1 = data.get("msg1", "")[:120]
            if rt_cd == "0":
                o = data.get("output", {})
                lines.append(f"✅ 매수가능 ({tr_id}) [AAPL 기준]")
                lines.append(f"  ord_psbl_frcr: ${_sf(o.get('ord_psbl_frcr_amt')):.2f}")
                lines.append(f"  ovrs_ord_psbl: ${_sf(o.get('ovrs_ord_psbl_amt')):.2f}")
                # 모든 필드 dump
                for k, v in o.items():
                    if k in ("ord_psbl_frcr_amt", "ovrs_ord_psbl_amt"):
                        continue
                    if v and v not in ("", "0", "0.00", 0):
                        lines.append(f"  {k}: {v}")
            else:
                lines.append(f"❌ 매수가능 ({tr_id})")
                lines.append(f"  rt_cd={rt_cd} msg: {msg1}")
        except Exception as e:
            lines.append(f"❌ 매수가능 EXC: {type(e).__name__}: {str(e)[:100]}")

        # v3.8: output2 USD 항목 모든 필드 dump (진단용)
        try:
            tr_id = "VTRP6504R" if IS_PAPER else "CTRP6504R"
            data = api.get(
                "/uapi/overseas-stock/v1/trading/inquire-present-balance",
                tr_id,
                {
                    "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                    "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
                    "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
                },
            )
            if data.get("rt_cd") == "0":
                o2_list = data.get("output2", []) or []
                for entry in o2_list:
                    if isinstance(entry, dict) and (entry.get("crcy_cd") or "").upper() == "USD":
                        lines.append("─────────")
                        lines.append("<b>USD 항목 모든 필드 (진단)</b>")
                        for k, v in entry.items():
                            lines.append(f"  {k}: {v}")
                        break
        except Exception:
            pass

        telegram.send("\n".join(lines), dedup_sec=10)

    def cmd_diagnose():
        """v4.2: 순수 통계 깊은 분석 (AI 없이)."""
        if _journal is None:
            telegram.send("intelligence 모듈 미로드")
            return
        for bid in _all_kis_bot_ids():
            try:
                msg = _journal.deep_diagnose(bot_id=bid, days=30)
                telegram.send(msg, dedup_sec=30)
            except Exception as e:
                telegram.send(f"⚠️ /diagnose {bid} 오류: {e}")

    def cmd_news():
        """v5.0: KR 시장 뉴스 sentiment 즉시 분석."""
        try:
            import news as _news_mod
            telegram.send("📰 KR 뉴스 분석 중...")
            s = _news_mod.get_kr_market_sentiment()
            if s:
                telegram.send(_news_mod.format_market_sentiment_msg(s), dedup_sec=10)
            else:
                telegram.send("⚠️ 뉴스 분석 실패 (RSS 또는 Gemini 문제)")
        except Exception as e:
            telegram.send(f"⚠️ /news 오류: {type(e).__name__}: {e}")

    def cmd_scan_us():
        """v6.15: US 유니버스 진단. 50종 샘플 (확장된 유니버스 대응)."""
        try:
            telegram.send("🔍 US 스캔 진단 중... (50종 샘플, ~2분)")
            def _progress(i, total):
                if i > 1:
                    print(f"[SCAN_US] {i}/{total} 진행 중", flush=True)
            d = scanner_overseas.diagnose_overseas(
                sample_size=50, progress_callback=_progress)
            telegram.send(scanner_overseas.format_diagnose_msg(d), dedup_sec=10)
        except Exception as e:
            import traceback
            traceback.print_exc()
            telegram.send(f"⚠️ /scan_us 오류: {type(e).__name__}: {e}")

    def cmd_test_us():
        """v6.20: KIS 거래소 코드 매핑 검증 (실주문 X).

        inquire-psamount 로 dry-run 체크. 종목별 KIS 인식 여부 확인.
        """
        import trader_overseas as _ot
        # 가격조회 코드 → 주문 코드 매핑 정상 동작 검증
        from trader_overseas import _to_trade_excd

        samples = [
            ("NVDA",  "NAS", "엔비디아"),    # 가격코드 NAS → 주문 NASD
            ("JPM",   "NYS", "JP모간"),       # NYS → NYSE
            ("SPY",   "AMS", "S&P500 ETF"),   # AMS → AMEX
        ]
        lines = ["🧪 <b>KIS 거래소 코드 매핑 테스트</b>"]

        # 1) 매핑 함수 (정적)
        lines.append("\n1️⃣ 매핑 함수:")
        for src in ("NAS", "NYS", "AMS"):
            mapped = _to_trade_excd(src)
            lines.append(f"   {src} → {mapped}")

        # 2) KIS API 호출 (dry-run inquire-psamount)
        lines.append("\n2️⃣ KIS API 응답 (실주문 X):")
        from kis_auth import get as _api_get
        from config import ACCOUNT_NO, IS_PAPER
        parts = ACCOUNT_NO.split("-")
        acc_no = parts[0]
        acc_prod = parts[1] if len(parts) > 1 else "01"
        tr_id = "VTTT3007R" if IS_PAPER else "JTTT3007R"

        for ticker, exch_src, name in samples:
            mapped = _to_trade_excd(exch_src)
            try:
                data = _api_get(
                    "/uapi/overseas-stock/v1/trading/inquire-psamount",
                    tr_id,
                    {
                        "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                        "OVRS_EXCG_CD": mapped,
                        "OVRS_ORD_UNPR": "100",
                        "ITEM_CD": ticker,
                    },
                )
                rt = data.get("rt_cd", "?")
                msg = data.get("msg1", "")[:80]
                if rt == "0":
                    o = data.get("output", {})
                    avail = o.get("ord_psbl_frcr_amt", "?")
                    lines.append(
                        f"   ✅ {name}({ticker}/{mapped}) — 가용 ${avail}"
                    )
                else:
                    lines.append(
                        f"   ❌ {name}({ticker}/{mapped}) — rt={rt}: {msg}"
                    )
            except Exception as e:
                lines.append(
                    f"   ⚠️ {name}({ticker}/{mapped}) — 예외: {type(e).__name__}: {str(e)[:60]}"
                )

        lines.append("\n→ 모두 ✅ 면 v6.19 매핑 정상 작동")
        telegram.send("\n".join(lines))

    cmd_handlers = {
        "/review":  cmd_review,
        "/lessons": cmd_lessons,
        "/propose": cmd_propose,
        "/symbols": cmd_symbols,
        "/diagnose": cmd_diagnose,
        "/news":    cmd_news,
        "/scan_us": cmd_scan_us,
        "/test_us": cmd_test_us,
    }
    last_weekly_review_kst_date = ""
    last_summary_kst_hour = -1  # v3.9: 정각 리포트 (시간별 1회)
    last_news_report_kst_date = ""  # v5.0: 09:00 KST 시장 뉴스 (일 1회)
    last_rotation_check_kst_hour = -1  # v6.7: 매 시간 09:10 ~ 14:10 회전 체크

    while True:
        now = now_kst()
        t_hm = now.strftime("%H:%M")

        # ════ 텔레그램 명령 폴링 ═══════════════════════════════
        try:
            telegram.poll_commands(cmd_handlers)
        except Exception as e:
            print(f"[MAIN] poll_commands err: {e}")

        # ════ v4.0 통합 서킷 브레이커 (KRW+USD 합계 -7% 시 양쪽 정지) ═══
        # 매일 09:00 첫 진입 시점에 anchor 갱신
        if t_hm == "09:00" and total_day_anchor_krw == 0:
            total_day_anchor_krw = get_total_equity_krw()
            total_circuit_tripped = False
        # 매 5분마다 한 번 체크 (운영시간 내만)
        if (not total_circuit_tripped and total_day_anchor_krw > 0
                and now.minute % 5 == 0
                and (is_dom_market_hours() or is_os_market_hours())):
            current_total = get_total_equity_krw()
            if current_total > 0:
                loss_pct = (current_total - total_day_anchor_krw) / total_day_anchor_krw
                if loss_pct <= -TOTAL_DAILY_LOSS_CIRCUIT:
                    total_circuit_tripped = True
                    telegram.send_force(
                        f"🛑 <b>통합 서킷 발동 (KRW+USD)</b>\n"
                        f"총 잔고 손실 {loss_pct*100:+.2f}% ≤ "
                        f"-{TOTAL_DAILY_LOSS_CIRCUIT*100:.0f}%\n"
                        f"양쪽 시장 신규 진입 전부 중단"
                    )

        # ════ 일요일 자정 자동 주간 회고 ════════════════════════
        if (_agent is not None
                and now.weekday() == 6
                and now.hour == 0 and now.minute < 15):
            today_str = now.strftime("%Y-%m-%d")
            if today_str != last_weekly_review_kst_date:
                last_weekly_review_kst_date = today_str
                print(f"[MAIN] 자동 주간 회고 트리거")
                for bid in _all_kis_bot_ids():
                    _agent.weekly_review_async(
                        bot_id=bid,
                        send_telegram=lambda m: telegram.send(m, dedup_sec=60),
                    )

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
                    and not total_circuit_tripped
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
                            atr_pct=c.get("atr_pct"),  # v4.0 변동성 사이징
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
                if (is_os_scan_time() and not total_circuit_tripped
                        and elapsed(last_os_scan) >= SCAN_INTERVAL_SEC):
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

                # 진입 스캔 (전 미장 시간)
                # v6.24: 미국 휴장일 감지시 스캔 스킵 (자정 UTC 자동 리셋)
                _us_holiday = False
                try:
                    _us_holiday = trader_overseas.is_us_holiday_today()
                except Exception:
                    pass
                if _us_holiday:
                    # 4시간 dedup 으로 알림 (1회만 전달)
                    telegram.send(
                        f"🏖️ 미국 휴장일 — 미장 스캔 일시 중단",
                        dedup_sec=14400,
                    )
                    last_os_scan = now  # 스캔 카운트만 갱신, 실제 스캔 X
                elif (is_os_scan_time() and not total_circuit_tripped
                        and len(os_pos) < OS_MAX_POSITIONS
                        and elapsed(last_os_scan) >= SCAN_INTERVAL_SEC):
                        # v6.11: 스캔 시작 알림 (1시간 dedup)
                        telegram.send(
                            f"🔭 미장 스캔 시작 ({hhmm()} KST) — KIS 일봉 조회 중 (~1~3분)",
                            dedup_sec=3600,
                        )
                        try:
                            cands = scanner_overseas.scan_overseas_candidates(
                                exclude_tickers=list(os_pos.keys())
                            )
                        except Exception as e:
                            print(f"[MAIN] 해외 스캔 오류: {e}")
                            telegram.send(f"⚠️ 미장 스캔 오류: {type(e).__name__}: {str(e)[:100]}",
                                          dedup_sec=600)
                            cands = []
                        # v6.11: 결과 알림 — 0건도 표시 (스캔이 정상 실행됐는지 확인용)
                        try:
                            from strategy_overseas import get_os_regime as _gor
                            _regime = _gor().get("regime", "?")
                        except Exception:
                            _regime = "?"
                        if cands:
                            telegram.send(
                                f"🌙 미장 스캔 ({hhmm()} KST) — 후보 {len(cands)}종 [regime={_regime}]\n"
                                + ", ".join(f"{c['ticker']} ${c.get('price',0):.0f}"
                                            for c in cands[:5]),
                                dedup_sec=1800,
                            )
                        else:
                            telegram.send(
                                f"🌙 미장 스캔 ({hhmm()} KST) — 후보 0종 [regime={_regime}]\n"
                                f"전 종목 진입조건 (정배열/RSI/거래량/패턴) 탈락",
                                dedup_sec=1800,
                            )
                        bought_count = 0
                        for c in cands:
                            if len(os_pos) >= OS_MAX_POSITIONS:
                                break
                            res = trader_overseas.buy_overseas(
                                c["ticker"], c["name"], c["exchange"],
                                reason=f"[{c.get('regime','')}] {c['reason']}",
                                atr_pct=c.get("atr_pct"),  # v4.0
                            )
                            if res:
                                os_pos[c["ticker"]] = res
                                trade_count += 1
                                bought_count += 1
                        # v6.10/6.17: 후보 있는데 매수 0건이면 사유 알림 (1시간 dedup)
                        if cands and bought_count == 0:
                            try:
                                fail_msg = trader_overseas.get_last_buy_fail_msg()
                            except Exception:
                                fail_msg = ""
                            detail = f"\nKIS 응답: {fail_msg}" if fail_msg else ""
                            telegram.send(
                                f"⚠️ 후보 {len(cands)}종 발견했지만 매수 0건"
                                f"{detail}\n"
                                f"가능 원인: 시간외 (정규: 22:30~05:00 KST), "
                                f"가용잔고 부족, 또는 KIS 거부",
                                dedup_sec=3600,
                            )
                        last_os_scan = now

                # EOD (05:45 ~ 05:55)
                if is_os_eod_check() and not os_eod_done and os_pos:
                    print("[MAIN] 해외 EOD 체크")
                    closed = monitor_overseas.check_overseas_eod(os_pos)
                    for t in closed:
                        os_pos.pop(t, None)
                        trade_count += 1
                    os_eod_done = True

        # ════ 정각 KST 현황 요약 (시간별 1회, 운영시간 내만) ═══════════════════
        if (now.minute < 5
                and now.hour != last_summary_kst_hour
                and (is_dom_market_hours() or is_os_market_hours())):
            send_summary(dom_pos, os_pos, trade_count)
            last_summary_kst_hour = now.hour

        # ════ v5.0: 09:00 KST KR 시장 뉴스 sentiment (일 1회) ═════════════════
        today_str = now.strftime("%Y-%m-%d")
        if (now.hour == 9 and now.minute < 10
                and today_str != last_news_report_kst_date
                and is_trading_day(now)):
            try:
                import news as _news_mod
                s = _news_mod.get_kr_market_sentiment()
                if s:
                    telegram.send_force(_news_mod.format_market_sentiment_msg(s))
                    last_news_report_kst_date = today_str
            except Exception as e:
                print(f"[MAIN] 뉴스 sentiment err: {e}")

        # ════ v6.3/6.7: 매 시간 회전 체크 (09:10, 10:10, ..., 14:10) ═══════
        # 점수 차 ≥ 20점 임계치가 자체 필터 — 정말 큰 변동 시만 트리거
        # 캐시 (10분 TTL) 덕에 비용 거의 0
        if (9 <= now.hour <= 14 and 10 <= now.minute < 20
                and now.hour != last_rotation_check_kst_hour
                and is_trading_day(now)
                and DOM_STRATEGY_MODE == "clenow"
                and dom_pos):
            try:
                import strategy_clenow_kr as _clenow
                signals = _clenow.check_rotation_signal(
                    dom_pos,
                    score_gap_min=ROTATION_SCORE_GAP_MIN,
                    min_hold_days=ROTATION_MIN_HOLD_DAYS,
                    n=CLENOW_WINDOW,
                    top_pct=CLENOW_TOP_PCT,
                    max_positions=CLENOW_MAX_POSITIONS,
                )
                if signals:
                    msg = _clenow.format_rotation_msg(
                        signals, alert_only=ROTATION_ALERT_ONLY)
                    telegram.send_force(msg)
                    # 알림만 모드: DB 에 시그널 기록 (사후 백테스트용)
                    if _journal is not None:
                        try:
                            for s in signals:
                                _journal.log_analysis(
                                    bot_id=f"kis_kr_clenow",
                                    kind="rotation_signal",
                                    summary=(
                                        f"sell {s['sell']['ticker']}({s['sell']['score']:.0f}) "
                                        f"→ buy {s['buy']['ticker']}({s['buy']['score']:.0f}) "
                                        f"gap={s['score_gap']:.0f}"
                                    ),
                                    details=str(s),
                                )
                        except Exception as je:
                            print(f"[MAIN] rotation log err: {je}")
                    # 실교체 모드 (1개월 후 활성화 가능)
                    if not ROTATION_ALERT_ONLY:
                        for s in signals:
                            sell_t = s["sell"]["ticker"]
                            buy_info = s["buy"]
                            sold_pos = dom_pos.get(sell_t)
                            if not sold_pos:
                                continue
                            if trader.sell_market(
                                sell_t, sold_pos["name"], sold_pos["qty"],
                                sold_pos["buy_price"],
                                f"회전 — 점수 {s['sell']['score']:.0f} → "
                                f"{buy_info['ticker']} {buy_info['score']:.0f} (+{s['score_gap']:.0f})"
                            ):
                                dom_pos.pop(sell_t, None)
                                # 신규 매수
                                bought = trader.buy_market(
                                    buy_info["ticker"], buy_info["name"],
                                    reason=f"회전 진입 (점수 {buy_info['score']:.0f})",
                                    expected_price=int(buy_info.get("close", 0)) or None,
                                    atr_pct=buy_info.get("atr_pct"),
                                )
                                if bought:
                                    bought["strategy_type"] = "CLENOW"
                                    dom_pos[buy_info["ticker"]] = bought
                                    trade_count += 2  # sell + buy
                last_rotation_check_kst_hour = now.hour
            except Exception as e:
                print(f"[MAIN] rotation 체크 err: {type(e).__name__}: {e}")

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

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
    """KIS overseas 보유 종목 조회 → os_pos dict.

    v6.31: 2단계 fallback.
    1차: inquire-balance (TTTS3012R) — 표준 보유종목 조회
    2차: inquire-present-balance (CTRP6504R) — 종합잔고 (백업)
    output1 이 비어있을 수 있어 두 endpoint 둘 다 시도.
    """
    parts = ACCOUNT_NO.split("-")
    acc_no = parts[0]
    acc_prod = parts[1] if len(parts) > 1 else "01"
    exch_map = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS",
                "TKSE": "TSE", "SEHK": "HKS"}
    holdings: dict = {}

    # 1차: 표준 보유종목 조회 (TTTS3012R) — 거래소별로 호출
    tr_id_v1 = "VTTS3012R" if IS_PAPER else "TTTS3012R"
    for exch_code in ("NASD", "NYSE", "AMEX"):
        try:
            data = api.get(
                "/uapi/overseas-stock/v1/trading/inquire-balance",
                tr_id_v1,
                {
                    "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                    "OVRS_EXCG_CD": exch_code,
                    "TR_CRCY_CD": "USD",
                    "CTX_AREA_FK200": "", "CTX_AREA_NK200": "",
                },
            )
            if data.get("rt_cd") != "0":
                print(f"[SYNC_US v1] {exch_code} 실패: {data.get('msg1', '')[:80]}")
                continue
            for item in data.get("output1", []):
                qty = float(item.get("ovrs_cblc_qty", 0) or 0)
                if qty <= 0:
                    continue
                ticker = item.get("ovrs_pdno", item.get("pdno", "")).strip()
                name = item.get("ovrs_item_name", item.get("prdt_name", ticker)).strip() or ticker
                avg_price = float(item.get("pchs_avg_pric", 0) or 0)
                if not ticker or avg_price <= 0:
                    continue
                # v1 응답엔 거래소 코드가 명시 안 됨 → 호출한 거래소 사용
                exchange = exch_map.get(exch_code, "NAS")
                holdings[ticker] = {
                    "ticker": ticker, "name": name, "exchange": exchange,
                    "qty": qty, "buy_price": avg_price,
                    "market": "overseas",
                }
        except Exception as e:
            print(f"[SYNC_US v1] {exch_code} 예외: {e}")

    if holdings:
        return holdings

    # 2차: 종합잔고 fallback (output1 / output2 둘 다 시도)
    try:
        tr_id_v2 = "VTRP6504R" if IS_PAPER else "CTRP6504R"
        data = api.get(
            "/uapi/overseas-stock/v1/trading/inquire-present-balance",
            tr_id_v2,
            {
                "CANO": acc_no, "ACNT_PRDT_CD": acc_prod,
                "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
                "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
            },
        )
        if data.get("rt_cd") != "0":
            print(f"[SYNC_US v2] 잔고 조회 실패: {data.get('msg1', '')[:120]}")
            return holdings
        for item in data.get("output1", []):
            qty = float(item.get("ovrs_cblc_qty", 0) or 0)
            if qty <= 0:
                continue
            ticker = item.get("pdno", "").strip()
            name = item.get("prdt_name", ticker).strip() or ticker
            avg_price = float(item.get("pchs_avg_pric", 0) or 0)
            exchange = (item.get("ovrs_excg_cd", "") or "NASD").strip()
            if not ticker or avg_price <= 0:
                continue
            exchange = exch_map.get(exchange, "NAS")
            holdings[ticker] = {
                "ticker": ticker, "name": name, "exchange": exchange,
                "qty": qty, "buy_price": avg_price,
                "market": "overseas",
            }
    except Exception as e:
        print(f"[SYNC_US v2] 예외: {e}")
    return holdings


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
# v6.36: Bybit Phase 1+2 KIS 포팅 — 인텔리전스 강화
# ═══════════════════════════════════════════════════════
_kis_symbol_rest_until: dict[str, float] = {}  # ticker → epoch ts (휴식 종료)


def check_symbol_rest_kis(ticker: str) -> tuple[bool, str]:
    """v6.36: KIS 부진 심볼 자동 휴식 체크."""
    import time as _t
    rest_until = _kis_symbol_rest_until.get(ticker, 0.0)
    if _t.time() < rest_until:
        remaining_hr = (rest_until - _t.time()) / 3600
        return False, f"휴식중 ({remaining_hr:.1f}h 남음)"
    return True, ""


def maybe_rest_underperforming_kis(bot_ids: list = None):
    """v6.36: 지난 N일 손실 누적 큰 KIS 심볼 자동 휴식.
    매 시간 1회 호출.
    """
    if _journal is None:
        return
    import time as _t
    try:
        from config import (KIS_SYMBOL_REST_DAYS, KIS_SYMBOL_REST_LOSS_PCT,
                            KIS_SYMBOL_REST_HOURS)
    except ImportError:
        return
    if bot_ids is None:
        bot_ids = [f"kis_kr_{DOM_STRATEGY_MODE}", f"kis_us_{OS_STRATEGY_MODE}"]
    by_sym: dict[str, float] = {}
    for bid in bot_ids:
        try:
            rows = _journal.recent_trades(
                bot_id=bid,
                since_seconds=KIS_SYMBOL_REST_DAYS * 86400,
            )
        except Exception:
            continue
        for r in rows:
            sym = r.get("symbol", "")
            # KIS 는 pnl_pct 가 의미있음 (가격 비례)
            pnl_pct = float(r.get("pnl_pct", 0))
            by_sym[sym] = by_sym.get(sym, 0) + pnl_pct
    for sym, total_pct in by_sym.items():
        # pnl_pct 는 fractional (0.05 = 5%). 임계치 5% = -0.05 * count?
        # 단순화: 누적 -X% 합계 (절대값)
        threshold = KIS_SYMBOL_REST_LOSS_PCT / 100.0  # 5% → 0.05
        if total_pct <= -threshold:
            cur_rest = _kis_symbol_rest_until.get(sym, 0)
            if cur_rest < _t.time():
                _kis_symbol_rest_until[sym] = _t.time() + KIS_SYMBOL_REST_HOURS * 3600
                try:
                    telegram.send_force(
                        f"😴 [{sym}] 자동 휴식 — "
                        f"지난 {KIS_SYMBOL_REST_DAYS}일 누적 {total_pct*100:+.2f}%\n"
                        f"{KIS_SYMBOL_REST_HOURS}h 진입 차단"
                    )
                except Exception:
                    pass


def ai_entry_gate_kis(ticker: str, name: str, market: str,
                     reason: str, price: float) -> dict:
    """v6.36: KIS 진입 직전 AI 게이트.

    Returns: {"approved": bool, "reason": str, "risk": "low/med/high"}
    AI 비활성/quota 소진/오류 시 항상 approved=True.
    """
    if _agent is None:
        return {"approved": True, "reason": "AI off", "risk": "?"}
    try:
        from config import KIS_AI_GATE_ENABLED
        if not KIS_AI_GATE_ENABLED:
            return {"approved": True, "reason": "disabled", "risk": "?"}
        from intelligence import agent as _ag
        if _ag._quota_state.get("exhausted"):
            return {"approved": True, "reason": "quota out", "risk": "?"}
    except Exception:
        return {"approved": True, "reason": "AI err", "risk": "?"}

    prompt = (
        f"한국투자증권 자동 매수 직전 AI 게이트. JSON 만 응답.\n"
        f"종목: {name} ({ticker}) — {market}\n"
        f"현재가: {price}\n"
        f"진입 사유: {reason}\n\n"
        f"이 매수에 명확한 위험 (어닝 직전/소문/공매도 급증/큰 갭) 있나?\n"
        f'JSON: {{"approved": true|false, "reason": "20자내", "risk": "low|medium|high"}}'
    )
    try:
        from intelligence.agent import _call_gemini, _extract_json
        text, err = _call_gemini(prompt, want_json=True, timeout=12)
        if err or not text:
            return {"approved": True, "reason": err or "no resp", "risk": "?"}
        data = _extract_json(text) or {}
        return {
            "approved": bool(data.get("approved", True)),
            "reason": str(data.get("reason", ""))[:60],
            "risk": str(data.get("risk", "?")),
        }
    except Exception as e:
        return {"approved": True, "reason": f"exc: {e}", "risk": "?"}


def check_market_corr_kis(market: str) -> tuple[bool, str]:
    """v6.36: KOSPI / QQQ 약세 → 해당 시장 진입 차단."""
    try:
        from config import KIS_CORR_GATE_ENABLED
        if not KIS_CORR_GATE_ENABLED:
            return True, ""
    except ImportError:
        return True, ""

    try:
        if market == "kr":
            # KODEX 200 일봉 → 현재가 vs MA20
            from strategy_clenow_kr import get_kr_daily, _sma
            candles = get_kr_daily("069500", count=30, market_code="J")
            if len(candles) < 25:
                return True, ""
            closes = [c["close"] for c in candles]
            ma20 = _sma(closes, 20)
            today = closes[0]
            if ma20 > 0 and today < ma20 * 0.98:  # MA20 의 -2% 아래 = 약세
                return False, f"KOSPI 약세 (KODEX200 {today} < MA20×0.98)"
        elif market == "us":
            # QQQ 일봉 → 현재가 vs MA20
            from strategy_overseas import get_overseas_daily
            from strategy_clenow_kr import _sma
            candles = get_overseas_daily("QQQ", "NAS", count=30)
            if len(candles) < 25:
                return True, ""
            closes = [c["close"] for c in candles]
            ma20 = _sma(closes, 20)
            today = closes[0]
            if ma20 > 0 and today < ma20 * 0.98:
                return False, f"QQQ 약세 ({today:.2f} < MA20×0.98)"
    except Exception as e:
        print(f"[KIS corr check {market}] err: {e}")
        return True, ""
    return True, ""


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

    # v6.42: USD-KRW 환율 (display 용 — 실거래는 USD 그대로)
    import os as _os
    USD_KRW_RATE = float(_os.environ.get("USD_KRW_RATE", "1380"))

    # 헤더는 아래 손익 계산 후에 작성 (총자산 포함)
    lines = []

    # v6.39: 국내/해외 시장별 누적 PnL 집계
    dom_total_pnl_krw = 0
    dom_total_cost = 0
    os_total_pnl_usd = 0.0
    os_total_cost = 0.0

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
            dom_total_pnl_krw += (cur - buy) * qty
            dom_total_cost += buy * qty
        # 국내 합계
        dom_pnl_pct = (dom_total_pnl_krw / dom_total_cost * 100) if dom_total_cost > 0 else 0
        dom_em = "📈" if dom_total_pnl_krw >= 0 else "📉"
        lines.append(
            f"  {dom_em} <b>국내 합계: ₩{dom_total_pnl_krw:+,.0f} "
            f"({dom_pnl_pct:+.2f}%)</b>"
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
            os_total_pnl_usd += (cur - buy) * qty
            os_total_cost += buy * qty
        # 해외 합계
        os_pnl_pct = (os_total_pnl_usd / os_total_cost * 100) if os_total_cost > 0 else 0
        os_em = "📈" if os_total_pnl_usd >= 0 else "📉"
        lines.append(
            f"  {os_em} <b>해외 합계: ${os_total_pnl_usd:+.2f} "
            f"({os_pnl_pct:+.2f}%)</b>"
        )

    if not dom_pos and not os_pos:
        lines.append("\n포지션: 없음")

    # v6.42: 총자산 헤더 — 가장 위에 삽입
    krw_total = bal.get('total_eval', 0) if bal else 0  # KRW 계좌 총평가
    krw_available = bal.get('available', 0) if bal else 0
    krw_eval_profit = bal.get('eval_profit', 0) if bal else 0
    krw_profit_pct = bal.get('profit_rate', 0) if bal else 0

    # USD 주식 평가액 (현재가 × 수량 합계, 위 루프에서 계산됨)
    # os_stock_value_usd: 해외 보유 종목 현재 평가액
    os_stock_value_usd = 0.0
    if os_pos:
        # 위 루프에서 cur 값을 못 가져와서 다시 계산하는 대신 cost+pnl 로 추정
        os_stock_value_usd = os_total_cost + os_total_pnl_usd
    usd_total = usd_avail + os_stock_value_usd
    usd_total_krw = usd_total * USD_KRW_RATE

    grand_total_krw = krw_total + usd_total_krw

    em_total = "📈" if krw_eval_profit >= 0 else "📉"
    header_lines = [
        f"⏰ <b>{hhmm()} KST</b>",
        f"💎 <b>총자산: ₩{grand_total_krw:,.0f}</b> "
        f"(USD→KRW @ {USD_KRW_RATE:.0f})",
        f"🇰🇷 KRW ₩{krw_total:,} (현금 ₩{krw_available:,})",
        f"🇺🇸 USD ${usd_total:.2f} "
        f"(현금 ${usd_avail:.2f}, 주식 ${os_stock_value_usd:.2f}) "
        f"≈ ₩{usd_total_krw:,.0f}",
        f"{em_total} 손익 ₩{krw_eval_profit:+,} ({krw_profit_pct:+.2f}%)",
    ]
    lines = header_lines + lines

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

    def cmd_sync_us():
        """v6.31: US 보유 종목 재동기화 (기존 보유 인식 안 될 때 수동 트리거)."""
        try:
            telegram.send("♻️ US 보유 재동기화 중...")
            us = load_us_holdings()
            if not us:
                telegram.send("⚠️ US 보유 0종 — KIS 응답에 잔고 없음 (또는 endpoint 실패)")
                return
            # 현재 os_pos 에 누락된 종목만 추가
            added = []
            for t, p in us.items():
                if t not in os_pos:
                    os_pos[t] = p
                    added.append(t)
            lines = [f"♻️ US 보유 {len(us)}종 동기화 완료"]
            for t, p in us.items():
                qd = f"{p['qty']:.4f}" if isinstance(p['qty'], float) and p['qty'] != int(p['qty']) else f"{int(p['qty'])}"
                tag = " 🆕" if t in added else ""
                lines.append(f"   {p['name']}({t}) {qd}주 @ ${p['buy_price']:.2f}{tag}")
            telegram.send("\n".join(lines))
        except Exception as e:
            telegram.send(f"⚠️ /sync_us 오류: {type(e).__name__}: {e}")

    def cmd_universe():
        """v6.48: 현재 Clenow top 20 종목 점수 표시 — 유니버스 다양성 확인용."""
        try:
            import strategy_clenow_kr as _clenow
            from config import CLENOW_WINDOW, CLENOW_EXIT_MA, DOM_UNIVERSE_LIMIT
            telegram.send("📊 Clenow top 20 스캔 중 (~2분)...")

            universe = _clenow.KR_UNIVERSE_TOP350[:DOM_UNIVERSE_LIMIT]
            scored = []
            n = CLENOW_WINDOW
            for ticker, name in universe:
                try:
                    candles = _clenow.get_kr_daily(ticker, count=n + 10)
                    if len(candles) < n:
                        continue
                    closes = [c["close"] for c in candles]
                    score = _clenow.clenow_score(closes, n)
                    if score != score:  # NaN
                        continue
                    ma50 = _clenow._sma(closes, CLENOW_EXIT_MA)
                    above_ma = closes[0] > ma50
                    scored.append({
                        "ticker": ticker, "name": name,
                        "score": float(score), "close": closes[0],
                        "above_ma50": above_ma,
                    })
                except Exception:
                    continue
            scored.sort(key=lambda x: -x["score"])
            top20 = scored[:20]

            held = set(dom_pos.keys())
            lines = [
                f"📊 <b>Clenow Top 20</b> (유니버스 {len(universe)}종 / 점수매김 {len(scored)})",
                f"━━━━━━━━━━━━━━",
            ]
            for i, s in enumerate(top20, 1):
                tag = ""
                if s["ticker"] in held:
                    tag = " ✅ 보유"
                elif not s["above_ma50"]:
                    tag = " ⚠️ MA50 이탈"
                lines.append(
                    f"{i}. {s['name']}({s['ticker']}) "
                    f"점수 {s['score']:.0f} @ ₩{s['close']:,.0f}{tag}"
                )
            lines.append("")
            lines.append(f"💡 보유 {len(held)}종 / 최대 {CLENOW_MAX_POSITIONS}종")
            telegram.send("\n".join(lines), dedup_sec=10)
        except Exception as e:
            import traceback
            traceback.print_exc()
            telegram.send(f"⚠️ /universe 오류: {type(e).__name__}: {e}")

    def cmd_chart():
        """v6.56/6.59: 일목균형표 + 추세선 + 손절/익절 라인.
        사용법: /chart 005930
                /chart NVDA 130 125 140  (진입/손절/익절)
        """
        raw = telegram._last_args.strip() if telegram._last_args else ""
        parts = raw.split()
        ticker = parts[0].upper() if parts else ""
        # v6.59: 추가 숫자 = entry / sl / tp
        entry = sl = tp = 0.0
        nums = []
        for p in parts[1:]:
            try:
                nums.append(float(p.replace(",", "")))
            except ValueError:
                pass
        if len(nums) >= 1:
            entry = nums[0]
        if len(nums) >= 2:
            sl = nums[1]
        if len(nums) >= 3:
            tp = nums[2]
        if not ticker:
            telegram.send("사용법: /chart [티커]\n"
                          "기본: /chart 005930\n"
                          "라인: /chart NVDA 130 125 140 (진입 손절 익절)")
            return
        is_kr = ticker.isdigit() and len(ticker) == 6
        is_us = ticker.isalpha() and 1 <= len(ticker) <= 5
        if not (is_kr or is_us):
            telegram.send(f"⚠️ 인식 불가: {ticker}")
            return
        telegram.send(f"📈 {ticker} 차트 생성 중 (~30초)...")
        try:
            import chart as _chart
            from strategy_clenow_kr import get_kr_daily
            from strategy_overseas import get_overseas_daily
            if is_kr:
                candles = get_kr_daily(ticker, count=180, market_code="J")
                label = f"{ticker} (KR) — Ichimoku + Trendlines"
            else:
                candles = get_overseas_daily(ticker, "NAS", count=180)
                label = f"{ticker} (US) — Ichimoku + Trendlines"
            if len(candles) < 60:
                telegram.send(f"⚠️ {ticker} 데이터 부족 ({len(candles)}일)")
                return
            png = _chart.make_chart(candles, label, is_crypto=False,
                                    entry=entry, sl=sl, tp=tp)
            if png:
                telegram.send_photo(png, caption=f"📈 {ticker} 일목균형표 + 추세선")
                # v6.58/6.59: 해설 + 단기/장기 + 손절/익절 R:R
                try:
                    analysis = _chart.chart_analysis(candles, ticker, is_crypto=is_us,
                                                     entry=entry, sl=sl, tp=tp)
                    telegram.send_force(analysis)
                except Exception as ae:
                    print(f"[chart_analysis err] {ae}")
            else:
                telegram.send("⚠️ 차트 생성 실패")
        except Exception as e:
            import traceback
            traceback.print_exc()
            telegram.send(f"⚠️ /chart 오류: {type(e).__name__}: {e}")

    def cmd_analyze():
        """v6.51: 임의 종목 기술적 분석 (KR/US 자동 판별).
        사용법: /analyze 005930 또는 /analyze NVDA
        """
        ticker = telegram._last_args.strip().upper() if telegram._last_args else ""
        if not ticker:
            telegram.send(
                "사용법: <code>/analyze [티커]</code>\n"
                "예) /analyze 005930 (KR)\n"
                "     /analyze NVDA (US)"
            )
            return

        # 시장 판별
        is_kr = ticker.isdigit() and len(ticker) == 6
        is_us = ticker.isalpha() and 1 <= len(ticker) <= 5

        if not (is_kr or is_us):
            telegram.send(f"⚠️ 인식 불가: <code>{ticker}</code>\n"
                          f"KR: 6자리 숫자 / US: 1~5자 알파벳")
            return

        telegram.send(f"📊 {ticker} 분석 중...")

        try:
            from strategy_clenow_kr import get_kr_daily, _sma
            from strategy_overseas import get_overseas_daily

            if is_kr:
                candles = get_kr_daily(ticker, count=210, market_code="J")
                market_label = "🇰🇷 KR"
                cur_symbol = "₩"
            else:
                # US: NAS / NYS / AMS 자동 fallback (get_overseas_daily 가 처리)
                candles = get_overseas_daily(ticker, "NAS", count=210)
                market_label = "🇺🇸 US"
                cur_symbol = "$"

            if len(candles) < 30:
                telegram.send(f"⚠️ {ticker} 일봉 데이터 부족 ({len(candles)}일)")
                return

            closes = [c["close"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            vols = [c.get("volume", 0) for c in candles]
            today = closes[0]

            ma20 = _sma(closes, 20)
            ma50 = _sma(closes, 50)
            ma200 = _sma(closes, 200) if len(closes) >= 200 else 0

            # RSI 14
            gains, losses = [], []
            for i in range(14):
                if i + 1 < len(closes):
                    diff = closes[i] - closes[i + 1]
                    gains.append(max(diff, 0))
                    losses.append(max(-diff, 0))
            ag = sum(gains) / 14 if gains else 0
            al = sum(losses) / 14 if losses else 0
            rsi = 100 - 100 / (1 + ag / al) if al > 0 else 50

            # BB (20, 2)
            sma20 = ma20
            if len(closes) >= 20:
                var = sum((c - sma20) ** 2 for c in closes[:20]) / 20
                std = var ** 0.5
                bb_upper = sma20 + 2 * std
                bb_lower = sma20 - 2 * std
                bb_pos = (today - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
            else:
                bb_upper = bb_lower = today
                bb_pos = 0.5

            # 20일 고점/저점
            high_20 = max(highs[:20]) if len(highs) >= 20 else today
            low_20 = min(lows[:20]) if len(lows) >= 20 else today

            # 거래량 비율
            avg_vol = sum(vols[1:21]) / 20 if len(vols) >= 21 else (sum(vols) / max(len(vols), 1))
            today_vol = vols[0]
            vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0

            # ATR 14
            trs = []
            for i in range(min(14, len(candles) - 1)):
                h = highs[i]
                low = lows[i]
                pc = closes[i + 1] if i + 1 < len(closes) else closes[i]
                trs.append(max(h - low, abs(h - pc), abs(low - pc)))
            atr = sum(trs) / len(trs) if trs else 0
            atr_pct = (atr / today * 100) if today > 0 else 0

            # 추세 평가
            if ma200 > 0 and ma50 > ma200 and today > ma50:
                trend_label = "🟢 강세 (정배열)"
            elif today > ma50:
                trend_label = "🟡 단기강세"
            elif today < ma50 and ma50 < ma200:
                trend_label = "🔴 약세 (역배열)"
            else:
                trend_label = "⚪ 혼조"

            # RSI 평가
            if rsi >= 70:
                rsi_label = "🔥 과열"
            elif rsi >= 50:
                rsi_label = "🟢 양호"
            elif rsi >= 30:
                rsi_label = "🟡 약세"
            else:
                rsi_label = "❄️ 과매도"

            # 포맷
            def fmt_price(p):
                if is_kr:
                    return f"₩{p:,.0f}"
                return f"${p:.2f}"

            ma200_str = fmt_price(ma200) if ma200 > 0 else "N/A"
            lines = [
                f"📊 <b>{ticker} 분석</b> {market_label}",
                f"━━━━━━━━━━━━━━",
                f"현재가: {fmt_price(today)}",
                f"추세: {trend_label}",
                f"  MA20  {fmt_price(ma20)}",
                f"  MA50  {fmt_price(ma50)}",
                f"  MA200 {ma200_str}",
                f"",
                f"RSI(14): {rsi:.0f} {rsi_label}",
                f"BB pos: {bb_pos:.2f} ({fmt_price(bb_lower)} ~ {fmt_price(bb_upper)})",
                f"ATR(14): {atr_pct:.2f}% (변동성)",
                f"",
                f"20일 고가: {fmt_price(high_20)}",
                f"20일 저가: {fmt_price(low_20)}",
                f"거래량: {vol_ratio:.2f}x 평균",
            ]

            # AI 분석 (선택)
            if _agent is not None:
                try:
                    from intelligence import agent as _ag
                    if not _ag._quota_state.get("exhausted"):
                        ai_prompt = (
                            f"한국어 1-2 문장으로 종목 {ticker} 단기 매수 매력도 평가.\n"
                            f"가격 {today:.2f}, MA20 {ma20:.2f}, MA50 {ma50:.2f}, "
                            f"MA200 {ma200:.2f}, RSI {rsi:.0f}, BB pos {bb_pos:.2f}, "
                            f"ATR {atr_pct:.2f}%, 거래량 {vol_ratio:.2f}x.\n"
                            f"매수/관망/매도 한 단어 권고 포함."
                        )
                        text, err = _ag._call_gemini(ai_prompt, timeout=10)
                        if text:
                            lines.append("")
                            lines.append(f"🧠 <b>AI 평가</b>: {text[:200]}")
                except Exception:
                    pass

            telegram.send("\n".join(lines))
        except Exception as e:
            import traceback
            traceback.print_exc()
            telegram.send(f"⚠️ /analyze 오류: {type(e).__name__}: {e}")

    cmd_handlers = {
        "/review":  cmd_review,
        "/lessons": cmd_lessons,
        "/propose": cmd_propose,
        "/symbols": cmd_symbols,
        "/diagnose": cmd_diagnose,
        "/news":    cmd_news,
        "/scan_us": cmd_scan_us,
        "/test_us": cmd_test_us,
        "/sync_us": cmd_sync_us,
        "/universe": cmd_universe,
        "/analyze": cmd_analyze,
        "/chart": cmd_chart,
    }

    # v6.52: KIS Multi-agent — Bybit 와 동일 패턴
    try:
        import claude_agent as kis_agent
        print("[MAIN] kis claude_agent 임포트 성공", flush=True)

        def cmd_kis_agent():
            if not kis_agent._enabled():
                telegram.send("⚠️ ANTHROPIC_API_KEY 미설정 (KIS Railway env 확인)")
                return
            telegram.send("🤖 KIS Claude Agent 분석 시작 (1~3분)...")
            try:
                # SDK 사전 검증
                try:
                    import anthropic as _anth_check
                    telegram.send(f"✓ anthropic SDK v{_anth_check.__version__}")
                except ImportError as ie:
                    telegram.send(f"❌ anthropic SDK 미설치: {ie}\nKIS Railway 재배포 필요 (requirements.txt)")
                    return
                ok = kis_agent.run_analysis()
                if not ok:
                    telegram.send("❌ run_analysis False — Railway 로그 확인")
            except Exception as e:
                import traceback as _tb
                print(f"[KIS agent err] {_tb.format_exc()}", flush=True)
                telegram.send(f"⚠️ Agent 예외: {type(e).__name__}: {str(e)[:200]}")

        def cmd_kis_agent_ping():
            """v6.53: Anthropic API 연결 분리 검증."""
            telegram.send("🏓 KIS Anthropic API ping...")
            try:
                from anthropic import Anthropic
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    telegram.send("❌ ANTHROPIC_API_KEY env 비어있음 (KIS Railway)")
                    return
                client = Anthropic(api_key=api_key, timeout=30.0)
                import time as _t
                t0 = _t.time()
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=50,
                    messages=[{"role": "user", "content": "Say 'pong'"}],
                )
                elapsed = _t.time() - t0
                text = response.content[0].text if response.content else "?"
                usage = response.usage
                telegram.send(
                    f"✓ Ping ({elapsed:.1f}s)\n"
                    f"응답: {text}\n"
                    f"tokens in={usage.input_tokens} out={usage.output_tokens}"
                )
            except Exception as e:
                import traceback as _tb
                print(f"[KIS ping err] {_tb.format_exc()}", flush=True)
                telegram.send(f"❌ Ping 실패: {type(e).__name__}: {str(e)[:300]}")

        def cmd_kis_research():
            telegram.send("🔬 KIS Research Agent 시작...")
            try:
                kis_agent.run_analysis(
                    user_prompt="KIS 양봇 (kr_clenow + us_swing) 7일 패턴 분석. "
                                "Clenow 파라미터 / US Swing 진입조건 개선 가설 + PR.",
                    mode="research",
                )
            except Exception as e:
                telegram.send(f"⚠️ Research 오류: {type(e).__name__}: {e}")

        def cmd_kis_risk():
            telegram.send("🛡️ KIS Risk Agent 시작...")
            try:
                kis_agent.run_analysis(
                    user_prompt="현재 KIS KR + US 보유 + 7일 PnL 위험 평가. "
                                "🟢🟡🔴 등급 + 권고. 집중도/drawdown 위주.",
                    mode="risk",
                )
            except Exception as e:
                telegram.send(f"⚠️ Risk 오류: {type(e).__name__}: {e}")

        def cmd_kis_portfolio():
            telegram.send("📈 KIS Portfolio Agent 시작...")
            try:
                kis_agent.run_analysis(
                    user_prompt="KR Clenow vs US Swing 30일 성과 비교 + "
                                "KOSPI/QQQ 시장 환경 + 자본 배분 권고.",
                    mode="portfolio",
                )
            except Exception as e:
                telegram.send(f"⚠️ Portfolio 오류: {type(e).__name__}: {e}")

        cmd_handlers["/agent"] = cmd_kis_agent
        cmd_handlers["/agent_ping"] = cmd_kis_agent_ping
        cmd_handlers["/research"] = cmd_kis_research
        cmd_handlers["/risk"] = cmd_kis_risk
        cmd_handlers["/portfolio"] = cmd_kis_portfolio
        print("[MAIN] KIS Multi-agent 명령 등록됨 (/agent /research /risk /portfolio)")
    except ImportError as e:
        print(f"[MAIN] KIS claude_agent 임포트 실패: {e}", flush=True)
        # 사용자도 알 수 있게 텔레그램에 한 번
        try:
            telegram.send_force(f"⚠️ KIS Multi-agent 비활성: {e}")
        except Exception:
            pass
    except Exception as e:
        import traceback
        print(f"[MAIN] KIS Multi-agent setup err: {traceback.format_exc()}", flush=True)
        try:
            telegram.send_force(f"⚠️ KIS Multi-agent 셋업 오류: {type(e).__name__}: {e}")
        except Exception:
            pass
    last_weekly_review_kst_date = ""
    last_summary_kst_hour = -1  # v3.9: 정각 리포트 (시간별 1회)
    last_news_report_kst_date = ""  # v5.0: 09:00 KST 시장 뉴스 (일 1회)
    last_rotation_check_kst_hour = -1  # v6.7: 매 시간 09:10 ~ 14:10 회전 체크
    # v6.40: 회전 매도 후 24h 재매수 차단 (같은 루프 스캐너 재픽업 방지)
    _rotation_sold_until: dict[str, float] = {}

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
                        # v6.40: 회전으로 매도된 종목 24h 재매수 차단
                        import time as _t
                        _now_ts = _t.time()
                        _rot_excluded = [
                            t for t, ts in _rotation_sold_until.items() if ts > _now_ts
                        ]
                        excluded_combined = list(dom_pos.keys()) + _rot_excluded
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
                                excluded_tickers=excluded_combined,
                                max_positions=max_pos - len(dom_pos),
                                max_price=price_ceiling,
                            )
                        else:
                            cands = scanner.scan_candidates(
                                exclude_tickers=excluded_combined,
                            )
                    except Exception as e:
                        print(f"[MAIN] 국내 스캔 오류: {e}")
                        cands = []
                    # v6.36: KOSPI 상관 게이트 (약세시 KR 진입 전체 차단)
                    ok_corr, corr_reason = check_market_corr_kis("kr")
                    if not ok_corr:
                        print(f"[MAIN] KR 상관 차단: {corr_reason}")
                        cands = []
                    for c in cands:
                        if len(dom_pos) >= max_pos:
                            break
                        # v6.36: 부진 심볼 휴식 체크
                        ok_rest, _ = check_symbol_rest_kis(c["ticker"])
                        if not ok_rest:
                            continue
                        # v6.36: AI 게이트
                        gate = ai_entry_gate_kis(
                            c["ticker"], c["name"], "KR",
                            c.get("reason", ""),
                            float(c.get("close", 0) or 0),
                        )
                        if not gate.get("approved", True):
                            telegram.send(
                                f"🚫 [{c['name']}] AI 게이트 거부\n"
                                f"사유: {gate.get('reason', '')}",
                                dedup_sec=300,
                            )
                            continue
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
                        # v6.36: QQQ 상관 게이트 (약세시 US 진입 전체 차단)
                        ok_corr_us, corr_us_reason = check_market_corr_kis("us")
                        if not ok_corr_us:
                            print(f"[MAIN] US 상관 차단: {corr_us_reason}")
                            cands = []
                        bought_count = 0
                        for c in cands:
                            if len(os_pos) >= OS_MAX_POSITIONS:
                                break
                            # v6.36: 부진 심볼 휴식 체크
                            ok_rest_us, _ = check_symbol_rest_kis(c["ticker"])
                            if not ok_rest_us:
                                continue
                            # v6.36: AI 게이트
                            gate_us = ai_entry_gate_kis(
                                c["ticker"], c["name"], "US",
                                c["reason"],
                                float(c.get("price", 0) or 0),
                            )
                            if not gate_us.get("approved", True):
                                telegram.send(
                                    f"🚫 [{c['name']}] AI 게이트 거부\n"
                                    f"사유: {gate_us.get('reason', '')}",
                                    dedup_sec=300,
                                )
                                continue
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

        # ════ 정각 KST 현황 요약 (v6.39: 24시간 매시간 — 시장 시간 외에도) ═══
        if (now.minute < 5
                and now.hour != last_summary_kst_hour):
            send_summary(dom_pos, os_pos, trade_count)
            last_summary_kst_hour = now.hour
            # v6.38: 자동 휴식 제거 (사용자 요청). 가중치 시스템이 대체.

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
                                # v6.40: 회전 매도 종목은 24h 재매수 차단
                                import time as _t
                                _rotation_sold_until[sell_t] = _t.time() + 24 * 3600
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
                                else:
                                    # v6.40: 회전 매수 실패 명시
                                    telegram.send_force(
                                        f"⚠️ 회전 매수 실패: {buy_info['name']}"
                                        f"({buy_info['ticker']}) @ ₩{buy_info.get('close', 0):,}\n"
                                        f"매도된 {s['sell']['ticker']} 는 24h 재진입 차단"
                                    )
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

"""Auto-rebalance bridge — signal (backtest_us.strategy_live) -> KIS orders.

Turns the weekly target weights into actual overseas (US ETF) orders through the
EXISTING kis.trader_overseas. Designed for the L1 (human-approved) flow:

  1. DRY-RUN (default): compute the plan from current KIS balance vs target,
     print it and Telegram it. NO orders are placed.  ← run this first / weekly.
  2. EXECUTE: set env REBALANCE_EXECUTE=true to actually place the buys/sells.
  3. Start in PAPER: set env KIS_PAPER=true (모의투자) until you trust it.

Crypto sleeves (BTC/ETH) are skipped here — those route to the bybit account.

Usage (on the machine that holds the KIS keys):
    python -m kis.rebalance_live                 # dry-run plan + telegram
    KIS_PAPER=true  REBALANCE_EXECUTE=true python -m kis.rebalance_live   # paper exec
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

# 경로 자가설정: repo root(backtest_us용) + kis/(config·trader_overseas 등 bare import용).
# 레일웨이/로컬 어디서 실행하든 import가 깨지지 않게 한다.
_HERE = os.path.dirname(os.path.abspath(__file__))      # .../kis
_ROOT = os.path.dirname(_HERE)                          # repo root
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_us.strategy_live import compute, SEC3X, build_context


# 퀀트봇(멀티에셋 전략 전용) 텔레그램 — 기존 kis 봇(TELEGRAM_TOKEN)과 분리.
# 이 전략의 신호/리밸런스 알림은 새 퀀트봇(TG_TOKEN/TG_CHAT_ID)으로만 보낸다.
QUANT_TG_TOKEN = os.environ.get("TG_TOKEN", "")
QUANT_TG_CHAT = os.environ.get("TG_CHAT_ID", "")


def quant_telegram(msg: str) -> None:
    """전용 퀀트봇으로 전송 (TG_TOKEN/TG_CHAT_ID). 미설정이면 콘솔만."""
    if not QUANT_TG_TOKEN or not QUANT_TG_CHAT:
        print("[퀀트봇] TG_TOKEN/TG_CHAT_ID 미설정 — 콘솔 출력만.")
        return
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{QUANT_TG_TOKEN}/sendMessage",
            data=json.dumps({"chat_id": QUANT_TG_CHAT, "text": msg}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"[퀀트봇] 전송 실패: {e}")


# KIS price-query exchange code per ticker (NAS=NASDAQ, AMS=NYSE Arca/AMEX).
EXCHANGE = {
    "SPY": "AMS", "QQQ": "NAS", "EEM": "AMS", "EFA": "AMS", "TLT": "NAS",
    "IEF": "NAS", "HYG": "AMS", "GLD": "AMS", "SLV": "AMS", "DBC": "AMS",
    "UUP": "AMS", "VNQ": "AMS",
    "TQQQ": "NAS", "TECL": "NAS",
    "SOXL": "AMS", "FAS": "AMS", "ERX": "AMS", "LABU": "AMS", "NUGT": "AMS",
}
SKIP = {"BTC-USD", "ETH-USD"}          # crypto -> bybit, not KIS
EXECUTE = os.environ.get("REBALANCE_EXECUTE", "false").lower() == "true"
# 점진(분할) 리밸런스: 매 실행마다 목표와의 격차 중 이 비율만 이동.
# 주1회 실행시 0.25 = ~4주 분할. 백테스트상 즉시보다 Sharpe↑·낙폭↓·회전율↓.
RAMP = float(os.environ.get("REBALANCE_RAMP", "0.25"))
# 매도(축소) 전용 속도. 백테스트(2010~, 위성): 분할매도가 즉시매도보다 Sharpe·CAGR
# 우위(0.76/39.7% vs 0.71/31.5%) — 200MA 이탈 다수가 회복되는 휩쏘라 즉시청산은
# 바닥매도가 됨. 기본은 매수와 동일(0.25). 낙폭 최우선이면 1.0(즉시, MDD -69→-60).
RAMP_SELL = float(os.environ.get("REBALANCE_RAMP_SELL", str(RAMP)))
# 전환 청산: 목표에 없는 기존 미국 보유종목을 전량 매도(현금화). 기본 off(안전).
LIQUIDATE = os.environ.get("LIQUIDATE", "false").lower() == "true"
# 주문 간 지연(초). 한 번에 십수개 주문을 쏘면 KIS 초당호출 제한에 걸려 api.post가
# 예외를 던지고 "❌매수실패"로 잡힌다. 각 매수는 잔고조회까지 동반해 호출이 많으므로
# 기본 0.6초 간격으로 throttle. 0으로 두면 지연 없음.
ORDER_DELAY_SEC = float(os.environ.get("REBALANCE_ORDER_DELAY", "0.6"))


def _fmt(plan, total_usd, paper):
    head = ("🧪 모의(PAPER) " if paper else "💵 실전 ") + ("실행" if EXECUTE else "계획(드라이런)")
    lines = [f"📊 멀티에셋 리밸런스 — {head}  (점진 {RAMP:.0%}/회)",
             f"총 평가액 ${total_usd:,.0f}", ""]
    for t, w, tgt_usd, cur_usd, step in plan:
        arrow = "매수" if step > 0 else ("매도" if step < 0 else "유지")
        lev = "⚡" if (t == "TQQQ" or t in SEC3X.values()) else ""
        lines.append(f"{t:5}{lev} 목표 {w:4.1%}(${tgt_usd:,.0f}) 현재 ${cur_usd:,.0f}"
                     f"  → 이번 {arrow} ${abs(step):,.0f}")
    return "\n".join(lines)


def main():
    import trader_overseas as ot
    paper = os.environ.get("KIS_PAPER", "false").lower() == "true"

    # 신호 직전 최신 시세로 자산 번들 갱신(stale 데이터 방지). 실패시 기존 번들 사용.
    if os.environ.get("REFRESH_BUNDLE", "true").lower() == "true":
        try:
            from backtest_us.assets_bundle import export as _export
            _export()
            print("[번들] 최신 시세로 갱신 완료")
        except Exception as e:  # noqa: BLE001
            print(f"[번들] 갱신 실패 — 기존 번들 사용: {e}")

    _, tgt, asof = compute()
    tgt = {t: w for t, w in tgt.items() if t not in SKIP}

    bal = ot.get_overseas_balance()
    total_usd = bal.get("total_eval_usd") or bal.get("available_usd") or 0.0
    holdings = bal.get("holdings", {}) or {}     # {ticker: {qty, eval_usd}} if available

    # 예산 상한: REBALANCE_BUDGET_USD>0 면 그 금액만 멀티에셋에 배분(소액 실전 테스트
    # 또는 계좌 일부만 운용). 0이면 계좌 전체.
    budget = float(os.environ.get("REBALANCE_BUDGET_USD", "0"))
    if budget > 0:
        total_usd = min(total_usd, budget)

    plan = []
    for t, w in sorted(tgt.items(), key=lambda x: -x[1]):
        tgt_usd = w * total_usd
        cur_usd = float((holdings.get(t) or {}).get("eval_usd", 0.0))
        gap = tgt_usd - cur_usd
        step = (RAMP if gap >= 0 else RAMP_SELL) * gap   # 이번 회차 이동분(매수/매도 속도 분리)
        plan.append((t, w, tgt_usd, cur_usd, step))

    # ---- 전환: 목표에 없는 기존 미국 보유종목 청산(LIQUIDATE=true) ----
    sells = []
    if LIQUIDATE:
        try:
            from main import load_us_holdings
            us = load_us_holdings() or {}
        except Exception as e:  # noqa: BLE001
            us = {}
            print(f"[청산] 보유조회 실패: {e}")
        for tk, pos in us.items():
            if tk in tgt or tk in SKIP:
                continue                       # 목표 종목은 유지(리밸런스가 처리)
            sells.append(pos)

    msg = _fmt(plan, total_usd, paper)
    if sells:
        msg += "\n\n🧹 기존종목 청산(목표 외):\n" + "\n".join(
            f"  {p['ticker']:5} {p['qty']:g}주 전량매도" for p in sells)
    try:
        msg += "\n" + build_context(tgt)         # 왜 이 비중인지 + 시장상황
    except Exception as e:  # noqa: BLE001
        print(f"[설명 생성 실패] {e}")
    print(msg)
    quant_telegram(msg)          # 전용 퀀트봇으로 (기존 kis 봇과 분리)

    if not EXECUTE:
        print("\n[dry-run] REBALANCE_EXECUTE=true 로 실행하면 실제 주문합니다. "
              "처음엔 KIS_PAPER=true 모의로 시작하세요. "
              "기존종목 청산은 LIQUIDATE=true 필요.")
        return

    # ---- EXECUTE 1) 기존종목 청산 (전량 매도) ----
    done = []
    for p in sells:
        if ORDER_DELAY_SEC > 0:
            time.sleep(ORDER_DELAY_SEC)        # KIS 초당호출 제한 회피(throttle)
        try:
            ot.sell_overseas(p["ticker"], p.get("name", p["ticker"]),
                             p.get("exchange", "NAS"), p["qty"],
                             p.get("buy_price", 0.0), reason="멀티에셋 전환 청산")
            done.append(f"매도 {p['ticker']} {p['qty']:g}주")
        except Exception as e:  # noqa: BLE001
            print(f"[청산] {p['ticker']} 실패: {e}")
            done.append(f"❌매도실패 {p['ticker']}")

    # ---- EXECUTE 2) 이번 회차 분할분만큼 매수 (진입/추가) ----
    for t, w, tgt_usd, cur_usd, step in plan:
        if step <= 5.0:                       # 매수분 미미하면 스킵
            continue
        if ORDER_DELAY_SEC > 0:
            time.sleep(ORDER_DELAY_SEC)        # KIS 초당호출 제한 회피(throttle)
        exch = EXCHANGE.get(t, "NAS")
        try:
            res = ot.buy_overseas(t, t, exch, reason="멀티에셋 점진 리밸런스",
                                  full_allocation_usd=step)
            if res:
                done.append(f"매수 {t} ${step:,.0f}")
            else:
                # KIS 거부 사유(msg1)를 텔레그램으로 끌어올림 (ETP 미신청·소수점 불가·시간외 등)
                why = ""
                try:
                    why = ot.get_last_buy_fail_msg()
                except Exception:  # noqa: BLE001
                    pass
                done.append(f"❌{t}: {why[:90] if why else '미체결/거부(사유미상)'}")
        except Exception as e:  # noqa: BLE001
            print(f"[order] {t} 실패: {e}")
            done.append(f"❌{t} 예외: {str(e)[:90]}")

    # ---- 체결 요약을 퀀트봇으로 ----
    if done:
        quant_telegram("✅ 멀티에셋 주문 실행\n" + "\n".join("  " + d for d in done))
    else:
        quant_telegram("ℹ️ 멀티에셋: 이번 회차 주문 없음(목표 도달/금액 미미)")


if __name__ == "__main__":
    main()

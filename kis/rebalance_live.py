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
import urllib.request

from backtest_us.strategy_live import compute, SEC3X


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
    from kis import trader_overseas as ot
    paper = os.environ.get("KIS_PAPER", "false").lower() == "true"

    _, tgt, asof = compute()
    tgt = {t: w for t, w in tgt.items() if t not in SKIP}

    bal = ot.get_overseas_balance()
    total_usd = bal.get("total_eval_usd") or bal.get("available_usd") or 0.0
    holdings = bal.get("holdings", {}) or {}     # {ticker: {qty, eval_usd}} if available

    plan = []
    for t, w in sorted(tgt.items(), key=lambda x: -x[1]):
        tgt_usd = w * total_usd
        cur_usd = float((holdings.get(t) or {}).get("eval_usd", 0.0))
        step = RAMP * (tgt_usd - cur_usd)        # 이번 회차 이동분(분할)
        plan.append((t, w, tgt_usd, cur_usd, step))

    msg = _fmt(plan, total_usd, paper)
    print(msg)
    quant_telegram(msg)          # 전용 퀀트봇으로 (기존 kis 봇과 분리)

    if not EXECUTE:
        print("\n[dry-run] REBALANCE_EXECUTE=true 로 실행하면 실제 주문합니다. "
              "처음엔 KIS_PAPER=true 모의로 시작하세요.")
        return

    # ---- EXECUTE: 이번 회차 분할분만큼 매수 (진입/추가). 매도 리밸런스는 다음 단계 ----
    for t, w, tgt_usd, cur_usd, step in plan:
        if step <= 5.0:                       # 매수분 미미하면 스킵
            continue
        exch = EXCHANGE.get(t, "NAS")
        try:
            ot.buy_overseas(t, t, exch, reason="멀티에셋 점진 리밸런스",
                            full_allocation_usd=step)
        except Exception as e:  # noqa: BLE001
            print(f"[order] {t} 실패: {e}")


if __name__ == "__main__":
    main()

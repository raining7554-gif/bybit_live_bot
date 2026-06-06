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

import os

from backtest_us.strategy_live import compute, SEC3X

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


def _fmt(plan, total_usd, paper):
    head = ("🧪 모의(PAPER) " if paper else "💵 실전 ") + ("실행" if EXECUTE else "계획(드라이런)")
    lines = [f"📊 멀티에셋 리밸런스 — {head}",
             f"총 평가액 ${total_usd:,.0f}", ""]
    for t, w, tgt_usd, cur_usd, act in plan:
        d = tgt_usd - cur_usd
        arrow = "신규/추가" if d > 0 else ("축소" if d < 0 else "유지")
        lev = "⚡" if (t == "TQQQ" or t in SEC3X.values()) else ""
        lines.append(f"{t:5}{lev} 목표 {w:4.1%} (${tgt_usd:,.0f})  현재 ${cur_usd:,.0f}  → {arrow} ${abs(d):,.0f}")
    return "\n".join(lines)


def main():
    from kis import trader_overseas as ot
    try:
        from kis import telegram as tg
    except Exception:
        tg = None
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
        plan.append((t, w, tgt_usd, cur_usd, tgt_usd - cur_usd))

    msg = _fmt(plan, total_usd, paper)
    print(msg)
    if tg is not None:
        try:
            tg.send_force(msg)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] skip: {e}")

    if not EXECUTE:
        print("\n[dry-run] REBALANCE_EXECUTE=true 로 실행하면 실제 주문합니다. "
              "처음엔 KIS_PAPER=true 모의로 시작하세요.")
        return

    # ---- EXECUTE: buys to reach target (v1: 진입/추가만; 매도 리밸런스는 다음 단계) ----
    for t, w, tgt_usd, cur_usd, diff in plan:
        if diff <= 5.0:                       # 이미 충분히 보유
            continue
        exch = EXCHANGE.get(t, "NAS")
        try:
            ot.buy_overseas(t, t, exch, reason="멀티에셋 리밸런스",
                            full_allocation_usd=diff)
        except Exception as e:  # noqa: BLE001
            print(f"[order] {t} 실패: {e}")


if __name__ == "__main__":
    main()

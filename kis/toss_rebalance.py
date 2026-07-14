"""멀티에셋 리밸런스 — 신호(backtest_us.strategy_live) → 토스증권 주문.

KIS 브리지(rebalance_live)의 토스 버전. 토스는 소수점 매매를 지원하므로 훨씬 단순하다:
  - 저가 share-class 치환(SPLG 등) 불필요 — SPY·QQQ·GLD를 그대로 거래
  - 온주 반올림·1주 floor 없음 — 목표 달러만큼 정확히 매수(orderAmount)
  - 매수는 금액(USD), 매도는 수량(소수점). 둘 다 미국 정규장에만 접수.

  DRY-RUN(기본): 계획만 계산·전송. REBALANCE_EXECUTE=true 로 실제 주문.
    BROKER=toss python -m kis.toss_rebalance
"""
from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_us.strategy_live import compute, build_context
from rebalance_live import quant_telegram          # 전용 퀀트봇 텔레그램 재사용
import toss_trader as tt
from toss_auth import TossError

SKIP = {"BTC-USD", "ETH-USD"}                        # crypto → bybit
EXECUTE = os.environ.get("REBALANCE_EXECUTE", "false").lower() == "true"
RAMP = float(os.environ.get("REBALANCE_RAMP", "0.25"))
RAMP_SELL = float(os.environ.get("REBALANCE_RAMP_SELL", str(RAMP)))
LIQUIDATE = os.environ.get("LIQUIDATE", "false").lower() == "true"
ORDER_DELAY_SEC = float(os.environ.get("REBALANCE_ORDER_DELAY", "0.4"))
MIN_ORDER_USD = float(os.environ.get("TOSS_MIN_ORDER_USD", "1.0"))


def _fmt(plan, total_usd):
    head = ("💵 실전 " if EXECUTE else "🧪 ") + ("실행" if EXECUTE else "계획(드라이런)")
    lines = [f"📊 멀티에셋 리밸런스(토스) — {head}  (점진 {RAMP:.0%}/회)",
             f"총 운용 ${total_usd:,.0f}", ""]
    for sym, w, tgt_usd, cur_usd, step in plan:
        arrow = "매수" if step > 0 else ("매도" if step < 0 else "유지")
        lines.append(f"{sym:5} 목표 {w:4.1%}(${tgt_usd:,.0f}) 현재 ${cur_usd:,.0f}"
                     f"  → 이번 {arrow} ${abs(step):,.0f}")
    return "\n".join(lines)


def _account_status(overview, total_usd, cash_usd, total_series):
    lines = ["💰 계좌 현황",
             f"· 총 평가액 ${total_usd:,.0f}  (보유 ${overview['market_value_usd']:,.0f} "
             f"+ 현금 ${cash_usd:,.0f})",
             f"· 평가손익 ${overview['pnl_usd']:+,.0f} ({overview['pnl_rate']*100:+.1f}%)  "
             f"← 매입가 대비(현재수익률)"]
    try:
        from backtest_us.metrics import _curve_stats
        st = _curve_stats((1 + total_series.loc["2010-01-01":]).cumprod(), "LIVE")
        lines.append(f"· 전략 전체기간(백테스트 2010~): CAGR {st['cagr']:+.0%} / "
                     f"MaxDD {st['mdd']:+.0%} / Sharpe {st['sharpe']:.2f}")
    except Exception as e:  # noqa: BLE001
        print(f"[성과 계산 실패] {e}")
    return "\n".join(lines)


def _coid(asof, side, sym):
    return f"mx-{asof}-{side}-{sym}"[:36]


def main():
    total, tgt, asof = compute()
    tgt = {t: w for t, w in tgt.items() if t not in SKIP}
    asof_s = str(asof.date())

    holdings = tt.get_us_holdings()
    overview = tt.get_holdings_overview()
    cash_usd = tt.get_buying_power_usd()
    holdings_usd = sum(h["eval_usd"] for h in holdings.values())
    account_total = holdings_usd + cash_usd

    total_usd = account_total
    budget = float(os.environ.get("REBALANCE_BUDGET_USD", "0"))
    if budget > 0:
        total_usd = min(total_usd, budget)

    plan = []
    for sym, w in sorted(tgt.items(), key=lambda x: -x[1]):
        tgt_usd = w * total_usd
        cur_usd = float((holdings.get(sym) or {}).get("eval_usd", 0.0))
        gap = tgt_usd - cur_usd
        step = (RAMP if gap >= 0 else RAMP_SELL) * gap
        plan.append((sym, w, tgt_usd, cur_usd, step))

    # 목표에 없는 미국 보유 → 청산 대상(LIQUIDATE)
    liq = [h for s, h in holdings.items() if s not in tgt and LIQUIDATE]

    msg = _fmt(plan, total_usd)
    if liq:
        msg += "\n\n🧹 목표 외 청산:\n" + "\n".join(
            f"  {h['symbol']:5} {h['qty']:g}주 전량매도" for h in liq)
    msg += "\n\n" + _account_status(overview, account_total, cash_usd, total)
    try:
        msg += "\n" + build_context(tgt)
    except Exception as e:  # noqa: BLE001
        print(f"[설명 생성 실패] {e}")
    print(msg)
    quant_telegram(msg)

    if not EXECUTE:
        print("\n[dry-run] REBALANCE_EXECUTE=true 로 실제 주문. 소액부터 검증하세요.")
        return

    done = []

    def _order(fn, label):
        if ORDER_DELAY_SEC > 0:
            time.sleep(ORDER_DELAY_SEC)
        try:
            fn()
            done.append(label)
        except TossError as e:
            print(f"[order] {label} 실패: {e}")
            done.append(f"❌{label}: {e.code} {e.message[:70]}")
        except Exception as e:  # noqa: BLE001
            print(f"[order] {label} 예외: {e}")
            done.append(f"❌{label} 예외: {str(e)[:70]}")

    # 1) 청산(목표 외 전량매도)
    for h in liq:
        if h["qty"] > 0:
            _order(lambda h=h: tt.sell_qty(h["symbol"], h["qty"], _coid(asof_s, "L", h["symbol"])),
                   f"청산매도 {h['symbol']} {h['qty']:g}주")

    # 2) 초과 비중 축소(trim) — 매수보다 먼저 현금 확보
    for sym, w, tgt_usd, cur_usd, step in plan:
        if step >= -MIN_ORDER_USD:
            continue
        pos = holdings.get(sym)
        if not pos or pos["qty"] <= 0 or pos["price"] <= 0:
            continue
        qty = min(abs(step) / pos["price"], pos["qty"])
        qty = int(qty * 1e6) / 1e6                    # 소수점 6자리 절삭
        if qty <= 0:
            continue
        _order(lambda sym=sym, qty=qty: tt.sell_qty(sym, qty, _coid(asof_s, "S", sym)),
               f"매도 {sym} {qty:g}주(축소)")

    # 3) 부족 비중 매수(금액 기반, 소수점)
    for sym, w, tgt_usd, cur_usd, step in plan:
        if step <= MIN_ORDER_USD:
            continue
        _order(lambda sym=sym, step=step: tt.buy_usd(sym, step, _coid(asof_s, "B", sym)),
               f"매수 {sym} ${step:,.0f}")

    if done:
        quant_telegram("✅ 멀티에셋(토스) 주문 실행\n" + "\n".join("  " + d for d in done))
    else:
        quant_telegram("ℹ️ 멀티에셋(토스): 이번 회차 주문 없음")


if __name__ == "__main__":
    main()

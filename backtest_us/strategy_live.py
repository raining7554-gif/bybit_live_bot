"""LIVE combined strategy — core + TQQQ + leveraged-sector satellite.

User-chosen package "섹터라이딩 혼합":  core 70% (multi-asset) + TQQQ 15% +
leveraged-sector rotation 15%. Outputs the actual weekly target weights in
TRADEABLE tickers, so the human can execute on KIS.

The leveraged-sector sleeve rotates among sectors that have a LIQUID 3x ETF
(price/trend judged on the unleveraged underlying in the bundle; held via the
3x ETF). Everything is trend-gated — a leveraged position is dropped to cash the
moment its underlying breaks its 200-day MA.

  python -m backtest_us.strategy_live
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .assets_bundle import load_assets
from .strategy_multiasset import compute as core_compute, _weekly
from .metrics import _curve_stats

TD = 252
COST = 0.0010
W_CORE, W_TQQQ, W_SEC = 0.70, 0.15, 0.15

# underlying (in bundle, for trend/momentum) -> tradeable 3x ETF (for execution)
SEC3X = {"SMH": "SOXL", "XLK": "TECL", "XLF": "FAS",
         "XLE": "ERX", "XBI": "LABU", "GDX": "NUGT"}
LETF_DRAG = 0.05   # annual cost of a 3x ETF (expense + financing), for backtest


def _trading(cm):
    return cm.reindex(cm["SPY"].dropna().index)


def sector3x_weights(cm, top_n=3, trend_ma=200, mom_win=126):
    und = [u for u in SEC3X if u in cm.columns]
    px = cm[und]
    trend = px > px.rolling(trend_ma, min_periods=trend_ma // 2).mean()
    mom = px / px.shift(mom_win) - 1.0
    score = mom.where(trend & px.notna())
    rank = score.rank(axis=1, ascending=False)
    held = (rank <= top_n) & score.notna()
    mpos = mom.where(held).clip(lower=0)
    rel = mpos.div(mpos.sum(axis=1).replace(0, np.nan), axis=0)
    inv = (held.sum(axis=1) / top_n).clip(upper=1.0)        # few qualify -> cash
    return rel.mul(inv, axis=0).fillna(0.0)                 # weights on UNDERLYINGS


def compute():
    cm = _trading(load_assets().sort_index())
    R = cm.pct_change()

    # 1) core (macro multi-asset)
    cw, core_ret, _ = core_compute()
    cw = cw.reindex(cm.index).ffill().fillna(0.0)
    core_ret = core_ret.reindex(cm.index).fillna(0.0)

    # 2) TQQQ sleeve (3x QQQ, on when QQQ>200MA)
    qqq = cm["QQQ"]
    tq_gate = _weekly(((qqq > qqq.rolling(200).mean()).astype(float)).to_frame("g"))["g"]
    tq_gate = tq_gate.shift(1).fillna(0.0)
    tqqq_ret = ((3 * R["QQQ"] - LETF_DRAG / TD) * tq_gate).fillna(0.0)

    # 3) leveraged-sector sleeve
    sw = _weekly(sector3x_weights(cm))
    swe = sw.shift(1).fillna(0.0)
    sec_ret = ((swe * (3 * R[sw.columns] - LETF_DRAG / TD)).sum(axis=1)).fillna(0.0)

    # combined daily return (fixed sleeve weights, weekly)
    total = (W_CORE * core_ret + W_TQQQ * tqqq_ret + W_SEC * sec_ret).fillna(0.0)

    # current target weights in tradeable tickers
    tgt = {}
    for a, w in (cw.iloc[-1] * W_CORE).items():
        if w > 0.005:
            tgt[a] = tgt.get(a, 0) + w
    if tq_gate.iloc[-1] > 0:
        tgt["TQQQ"] = tgt.get("TQQQ", 0) + W_TQQQ
    for u, w in (sw.iloc[-1] * W_SEC).items():
        if w > 0.003:
            tgt[SEC3X[u]] = tgt.get(SEC3X[u], 0) + float(w)
    return total, tgt, cw.index[-1]


def main():
    total, tgt, asof = compute()
    st = _curve_stats((1 + total.loc["2010-01-01":]).cumprod(), "LIVE")
    print(f"LIVE 섹터라이딩 혼합 (코어70+TQQQ15+섹터3x15, 2010~, net): "
          f"Sharpe={st['sharpe']:.2f} CAGR={st['cagr']:+.1%} MaxDD={st['mdd']:+.1%}")

    print(f"\n=== 이번 주 목표 비중 (실거래 종목) — {asof.date()} ===")
    cash = 1 - sum(tgt.values())
    for k, v in sorted(tgt.items(), key=lambda x: -x[1]):
        tag = " ⚡3x" if k in ("TQQQ",) or k in SEC3X.values() else ""
        print(f"  {k:6} {v:5.1%}{tag}")
    print(f"  현금   {max(cash,0):5.1%}")

    m = (1 + total.loc["2025-05-31":]).resample("ME").prod() - 1
    bal = 5_000_000
    print("\n최근 1년 월별 (500만원):")
    for dt, mr in m.items():
        bal *= 1 + mr
        print(f"  {dt.strftime('%Y-%m')}  {mr:+6.1%}   {bal:>12,.0f}원")
    print(f"  합계 {bal/5_000_000-1:+.1%}")


if __name__ == "__main__":
    main()

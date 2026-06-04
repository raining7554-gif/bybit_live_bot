"""Adaptive multi-state strategy — the synthesis of all research (ROADMAP [3a]-[3h]).

Everything we tested (stock-picking momentum, day-trade sleeves, long/short, hedges)
collapsed to ONE efficient lever: regime timing + a leverage dial. This module
expresses that as a state machine on price-derived market conditions:

  uptrend & healthy (not extended, above 50MA)   -> 2.0x   (ride it)
  uptrend & somewhat extended (+10..25% vs 250MA) -> 1.5x
  uptrend & frothy (>25%) or in a pullback         -> 1.0x   (top defense)
  downtrend (below 250MA)                          -> cash
  confirmed deep downtrend                         -> -0.5x  (small crash short)

It is survivorship-bias-free (PIT) and look-ahead-free (weekly decision, applied
next session). LIMITATION: signals are price-only — no news / order-flow. Those
are a discretionary human overlay, not modelled here.

  python -m backtest_us.strategy_adaptive          # stats + last-12-month table
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .research_fast import _load_matrices, _weekly_ffill, TD
from .metrics import _curve_stats

COST, FIN, BORROW = 0.0010, 0.040, 0.010   # 10bps trade, 4% financing, 1% borrow


def adaptive_exposure(spy: pd.Series) -> pd.Series:
    """Weekly target exposure (already shifted 1 day for no look-ahead)."""
    ma250, ma200, ma50 = (spy.rolling(n).mean() for n in (250, 200, 50))
    ext = spy / ma250 - 1
    up, a50 = (spy > ma250), (spy > ma50)
    e = (
        (up & a50 & (ext < 0.10)) * 2.0
        + (up & a50 & (ext >= 0.10) & (ext < 0.25)) * 1.5
        + (up & a50 & (ext >= 0.25)) * 1.0
        + (up & ~a50) * 1.0
        + ((spy < ma250) & (ma250.diff(20) < 0) & (ma50 < ma200)) * (-0.5)
    )
    return _weekly_ffill(e.astype(float), spy.index).shift(1).fillna(0)


def backtest(exp: pd.Series, mkt_ret: pd.Series) -> pd.Series:
    bor = (exp - 1).clip(lower=0)
    short = (-exp).clip(lower=0)
    return (exp * mkt_ret - bor * (FIN / TD) - short * (BORROW / TD)
            - COST * exp.diff().abs().fillna(0)).fillna(0)


def main():
    spy, sl = _load_matrices()
    mkt = spy.pct_change()
    exp = adaptive_exposure(spy)
    r = backtest(exp, mkt)

    st = _curve_stats((1 + r).cumprod(), "ADAPTIVE")
    print(f"ADAPTIVE  Sharpe={st['sharpe']:.2f}  CAGR={st['cagr']:+.1%}  MDD={st['mdd']:+.1%}")
    print(f"현재 지시 노출: {exp.iloc[-1]:.1f}x  (SPY {spy.iloc[-1]:.0f}, "
          f"vs250MA {(spy/spy.rolling(250).mean()-1).iloc[-1]:+.0%})")

    cap = 5_000_000
    m = (1 + r.loc["2025-05-31":]).resample("ME").prod() - 1
    print("\n최근 1년 월별 (500만원):")
    bal = cap
    for dt, mr in m.items():
        bal *= 1 + mr
        print(f"  {dt.strftime('%Y-%m')}  {mr:+6.1%}   {bal:>12,.0f}원")
    print(f"  합계 {bal/cap-1:+.1%}  ({bal:,.0f}원)")


if __name__ == "__main__":
    main()

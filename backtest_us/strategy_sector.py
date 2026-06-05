"""Sector / thematic momentum-rotation sleeve — the aggressive complement.

The macro core (strategy_multiasset) is broad and defensive; by design it does
NOT chase a single hot sector. This sleeve does the opposite: it LEANS INTO
whatever sectors money is flooding. "Flow" shows up in price, so we just rank
sector ETFs by trailing momentum and hold the strongest few that are in an
uptrend, dropping them the moment they break trend.

Rules (weekly):
  - candidate = sector ETF above its 200-day MA (uptrend);
  - rank candidates by 6-month return (relative strength);
  - hold the top `top_n`, momentum-weighted (lean into the strongest);
  - if fewer than top_n qualify, the rest is cash (risk-off).

Survivorship-free (liquid ETFs), look-ahead-free (weekly decide, apply next bar).

  python -m backtest_us.strategy_sector
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .assets_bundle import load_assets, SECTORS
from .strategy_multiasset import _weekly
from .metrics import _curve_stats

TD = 252
COST = 0.0010


def compute(trend_ma=200, mom_win=126, top_n=5):
    cm = load_assets().sort_index()
    cm = cm.reindex(cm["SPY"].dropna().index)        # trading-day calendar
    cols = [c for c in SECTORS if c in cm.columns]
    px = cm[cols]
    R = px.pct_change()

    trend = px > px.rolling(trend_ma, min_periods=trend_ma // 2).mean()
    mom = px / px.shift(mom_win) - 1.0               # 6-month relative strength
    score = mom.where(trend & px.notna())            # only uptrending candidates
    rank = score.rank(axis=1, ascending=False)
    held = (rank <= top_n) & score.notna()           # top_n strongest uptrends

    mpos = mom.where(held).clip(lower=0)             # momentum weight (lean into winners)
    rel = mpos.div(mpos.sum(axis=1).replace(0, np.nan), axis=0)   # relative weights, sum 1
    invested = (held.sum(axis=1) / top_n).clip(upper=1.0)         # few qualify -> hold cash
    w = rel.mul(invested, axis=0).fillna(0.0)

    w_wk = _weekly(w)
    we = w_wk.shift(1).fillna(0.0)
    port = (we * R).sum(axis=1) - COST * we.diff().abs().sum(axis=1).fillna(0)
    return w_wk, port.fillna(0.0)


def main():
    w, r = compute()
    st = _curve_stats((1 + r.loc["2008-01-01":]).cumprod(), "Sector-rotation")
    print(f"Sector rotation (2008~, net): Sharpe={st['sharpe']:.2f} "
          f"CAGR={st['cagr']:+.1%} MaxDD={st['mdd']:+.1%}")
    cur = w.iloc[-1]
    held = cur[cur > 0.005].sort_values(ascending=False)
    print(f"\n=== 지금 뜨는 섹터 (보유) — {w.index[-1].date()} ===")
    for k, v in held.items():
        print(f"  {k:6} {v:5.0%}")
    print(f"  현금 {1-held.sum():5.0%}")


if __name__ == "__main__":
    main()

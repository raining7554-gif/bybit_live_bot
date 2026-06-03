"""Sub-period robustness of the regime-timed EW strategies (gross, vectorised).

The single most important check before trusting a market-timer: is the edge
consistent across eras, or an artifact of one crisis (2008)? This slices the
daily return streams into booms and busts and reports Sharpe / MDD / return per
window for the two winners vs the EW & SPY baselines.

  python -m backtest_us.research_robust
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pit_universe import PIT_BENCHMARK
from .research_fast import _load_matrices, _weekly_ffill, TD


def _ew_ret(stocks_live):
    return stocks_live.pct_change().clip(upper=1.0).mean(axis=1)


def strat_series(spy, sl, regime_ma=250, breadth_ma=0):
    """Daily return series of a regime-timed (optionally breadth-scaled) EW book."""
    ew = _ew_ret(sl)
    exp = pd.Series(1.0, index=spy.index)
    if regime_ma:
        reg = (spy > spy.rolling(regime_ma).mean()).astype(float)
        exp = exp * _weekly_ffill(reg, spy.index)
    if breadth_ma:
        ma_s = sl.rolling(breadth_ma, min_periods=breadth_ma // 2).mean()
        brd = (sl > ma_s).sum(axis=1) / sl.notna().sum(axis=1)
        exp = exp * _weekly_ffill(brd, spy.index)
    exp = exp.shift(1).clip(0, 1).fillna(0)
    return (ew * exp).fillna(0.0)


def _win_stats(r):
    r = r.dropna()
    if len(r) < 30:
        return None
    ann = r.mean() * TD
    vol = r.std() * np.sqrt(TD)
    sh = ann / vol if vol > 0 else np.nan
    curve = (1 + r).cumprod()
    mdd = (curve / curve.cummax() - 1).min()
    return ann, vol, sh, float(mdd)


WINDOWS = [
    ("94-00 dot-com boom", "1994-01-01", "2000-03-23"),
    ("00-03 dot-com bust",  "2000-03-24", "2003-03-31"),
    ("03-07 bull",          "2003-04-01", "2007-10-09"),
    ("07-09 GFC",           "2007-10-10", "2009-03-09"),
    ("09-20 long bull",     "2009-03-10", "2020-02-19"),
    ("20 COVID crash",      "2020-02-20", "2020-03-23"),
    ("20-26 recent",        "2020-03-24", "2026-12-31"),
]


def main():
    spy, sl = _load_matrices()
    ew = _ew_ret(sl)
    series = {
        "EWreg250":      strat_series(spy, sl, 250, 0),
        "reg250+brd200": strat_series(spy, sl, 250, 200),
        "EW-universe":   ew,
        "SPY":           spy.pct_change(),
    }
    print(f"[robust] {sl.shape[1]} names; gross; Sharpe (and MDD) per era\n")
    names = list(series)
    print(f"{'window':<22}" + "".join(f"{n:>16}" for n in names))
    print("-" * (22 + 16 * len(names)))
    for label, a, b in WINDOWS:
        cells = []
        for n in names:
            st = _win_stats(series[n].loc[a:b])
            cells.append("   -" if st is None else f"{st[2]:>5.2f}/{st[3]*100:>5.0f}%")
        print(f"{label:<22}" + "".join(f"{c:>16}" for c in cells))
    print("-" * (22 + 16 * len(names)))
    # full-period row
    cells = []
    for n in names:
        st = _win_stats(series[n])
        cells.append(f"{st[2]:>5.2f}/{st[3]*100:>5.0f}%")
    print(f"{'FULL 1993-2026':<22}" + "".join(f"{c:>16}" for c in cells))
    print("\n(cell = Sharpe / MaxDD over the window)")


if __name__ == "__main__":
    main()

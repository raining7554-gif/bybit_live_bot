"""Vectorised strategy scan (seconds, gross of cost) off the committed bundle.

The per-name python engine is too slow for wide sweeps, so this evaluates the
regime-timed / trend-filtered EQUAL-WEIGHT family analytically on the close
matrix. Use it to RANK ideas; then validate the winner with the exact engine
(`research.py` / `run.py`) for net-of-cost, share-accurate numbers.

No look-ahead: every decision (regime on/off, trend membership) is made on day i
and applied to day i+1's return (`.shift(1)`). Survivorship-free via PIT mask.

  python -m backtest_us.research_fast
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pit_universe import load_pit_universe, PIT_BENCHMARK
from .data import BUNDLE_CLOSES
from .metrics import _curve_stats

TD = 252


def _load_matrices():
    cm = pd.read_csv(BUNDLE_CLOSES, index_col=0, parse_dates=True)
    spy = cm[PIT_BENCHMARK].dropna()
    master = spy.index
    stocks = cm.drop(columns=[PIT_BENCHMARK]).reindex(master)

    _, elig = load_pit_universe()
    listed = pd.DataFrame(False, index=master, columns=stocks.columns)
    for t in stocks.columns:
        win = elig.get(t)
        if win is None:
            continue
        start, end = win
        m = master >= start
        if end is not None:
            m &= master <= end
        listed[t] = m
    stocks_live = stocks.where(listed)
    return spy, stocks_live


def _stats(curve, name, pct_inv=np.nan):
    st = _curve_stats(curve, name)
    st["pct_inv"] = pct_inv
    return st


def evaluate(spy, stocks_live, regime_ma=200, trend_ma=0, weekly=True):
    """Return stats for a regime-timed EW strategy.

    trend_ma=0 -> hold ALL listed names (pure regime-timed beta);
    trend_ma>0 -> hold only names above their own `trend_ma` MA.
    """
    R = stocks_live.pct_change().clip(upper=1.0)

    # Membership decided on day i, applied day i+1.
    if trend_ma > 0:
        ma_s = stocks_live.rolling(trend_ma, min_periods=trend_ma // 2).mean()
        held = (stocks_live > ma_s).shift(1)
    else:
        held = stocks_live.shift(1).notna()
    ew = R.where(held).mean(axis=1)                      # equal-weight of held names

    # Index regime gate (SPY vs its MA), decided day i, applied day i+1.
    regime = (spy > spy.rolling(regime_ma).mean())
    if weekly:                                            # refresh decision weekly only
        wk = pd.Series(spy.index, index=spy.index).resample("W").last().dropna()
        keep = regime.index.isin(set(wk.values))
        regime = regime.where(keep).ffill()
    gate = regime.shift(1).fillna(False)

    strat = (ew * gate).fillna(0.0)
    curve = (1 + strat).cumprod()
    pct_inv = float(gate.mean())
    return _stats(curve, f"EWreg{regime_ma}" + (f"_tr{trend_ma}" if trend_ma else "_all"), pct_inv)


def baselines(spy, stocks_live):
    R = stocks_live.pct_change().clip(upper=1.0)
    ew = (1 + R.mean(axis=1).fillna(0)).cumprod()
    spyc = spy / spy.iloc[0]
    return _stats(ew, "EW-universe (buy&hold)"), _stats(spyc, f"{PIT_BENCHMARK} buy&hold")


def main():
    spy, sl = _load_matrices()
    print(f"[fast] {sl.shape[1]} names x {sl.shape[0]} days loaded\n")

    rows = []
    for rma in (100, 150, 200, 250):
        rows.append(evaluate(spy, sl, regime_ma=rma, trend_ma=0))
    for tma in (100, 150, 200):
        rows.append(evaluate(spy, sl, regime_ma=200, trend_ma=tma))

    ew, spyb = baselines(spy, sl)
    _print(rows + [ew, spyb], ew["sharpe"])


def _print(rows, ew_sh):
    cols = ["CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Calmar", "%inv"]
    keys = ["cagr", "ann_vol", "sharpe", "sortino", "mdd", "calmar", "pct_inv"]

    def c(st, k):
        v = st.get(k, np.nan)
        if v != v:
            return "  -"
        if k in ("cagr", "mdd"):
            return f"{v:+.1%}"
        if k in ("ann_vol", "pct_inv"):
            return f"{v:.0%}"
        return f"{v:.2f}"

    print("=" * 96)
    print(f"{'strategy':<26}" + "".join(f"{x:>8}" for x in cols) + "   vs EW")
    print("-" * 96)
    for st in rows:
        base = st["name"].startswith(("EW-universe", PIT_BENCHMARK))
        tag = "" if base else f"   {'WIN ' if st['sharpe'] > ew_sh else 'lose'} ({st['sharpe']-ew_sh:+.2f})"
        print(f"{st['name']:<26}" + "".join(f"{c(st,k):>8}" for k in keys) + tag)
    print("=" * 96)


if __name__ == "__main__":
    main()

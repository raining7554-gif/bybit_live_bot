"""Multi-asset trend-following — the production strategy (ROADMAP [3i]→).

Genuine diversification across asset CLASSES (equities / bonds / gold / commodities
/ FX / crypto), each gated by its own trend and risk-weighted. When one regime dies
another tends to trend, so the book rotates and the ride is smooth. This beat every
equity-only variant: Sharpe ~0.90, MaxDD ~-21% (2008-2026, net) vs SPY 0.64 / -52%.

Rules (weekly):
  - an asset is ELIGIBLE while its price is above its 200-day MA (own uptrend);
  - weight eligible assets by inverse 60d volatility (risk parity), cap per asset;
  - scale the whole book toward a target volatility (leverage dial, capped);
  - everything else sits in cash.

Survivorship-free assets (liquid ETFs + crypto), look-ahead-free (decide on the
weekly close, apply next session). Crypto weekend bars are folded into the next
trading day. LIMIT: price-only — news / flow are a human overlay.

  python -m backtest_us.strategy_multiasset        # current target weights + stats
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .assets_bundle import load_assets
from .metrics import _curve_stats

TD = 252
COST = 0.0010


def _weekly(df: pd.DataFrame) -> pd.DataFrame:
    wk = pd.Series(df.index, index=df.index).resample("W").last().dropna()
    keep = df.index.isin(set(wk.values))
    o = df.copy()
    o[~keep] = np.nan
    return o.ffill()


def compute(trend_ma=200, vol_win=60, cap=0.25, target_vol=0.10, lev_cap=1.0):
    """Return (weights, daily_returns, leverage) — weights are pre-leverage targets."""
    cm = load_assets().sort_index()
    from .assets_bundle import MACRO
    cm = cm[[c for c in MACRO if c in cm.columns]]   # CORE = macro only (sectors are a separate sleeve)
    cm = cm.reindex(cm["SPY"].dropna().index)        # align to trading days
    R = cm.pct_change()

    trend = cm > cm.rolling(trend_ma, min_periods=trend_ma // 2).mean()
    vol = R.rolling(vol_win, min_periods=vol_win // 2).std()
    iv = (1.0 / vol).where(trend & cm.notna())
    w = iv.div(iv.sum(axis=1), axis=0).clip(upper=cap)
    w = w.div(w.sum(axis=1), axis=0).fillna(0.0)     # 0 everywhere -> all cash
    w_wk = _weekly(w)

    we = w_wk.shift(1).fillna(0.0)
    port = (we * R).sum(axis=1) - COST * we.diff().abs().sum(axis=1).fillna(0)

    lev = pd.Series(1.0, index=cm.index)
    if target_vol:
        rv = port.rolling(40, min_periods=20).std() * np.sqrt(TD)
        lev = (target_vol / rv).clip(upper=lev_cap)
        lev_app = lev.shift(1).fillna(0)
        port = port * lev_app - COST * lev_app.diff().abs().fillna(0)
    return w_wk, port.fillna(0.0), lev


def main():
    w, r, lev = compute()
    st = _curve_stats((1 + r.loc["2008-01-01":]).cumprod(), "MultiAsset")
    print(f"MultiAsset trend (2008~, net):  Sharpe={st['sharpe']:.2f}  "
          f"CAGR={st['cagr']:+.1%}  MaxDD={st['mdd']:+.1%}")

    cur = w.iloc[-1]
    L = float(lev.iloc[-1])
    print(f"\n=== 이번 주 목표 비중 (레버리지 {L:.2f}x 적용 전) — {w.index[-1].date()} ===")
    held = cur[cur > 0.005].sort_values(ascending=False)
    for k, v in held.items():
        print(f"  {k:8} {v:5.0%}   (실제 {v*L:4.0%})")
    cash = 1 - held.sum()
    print(f"  현금     {cash:5.0%}")
    off = [a for a in w.columns if cur.get(a, 0) <= 0.005]
    print(f"  추세OFF: {', '.join(off)}")

    cap_won = 5_000_000
    m = (1 + r.loc["2025-05-31":]).resample("ME").prod() - 1
    print("\n최근 1년 월별 (500만원):")
    bal = cap_won
    for dt, mr in m.items():
        bal *= 1 + mr
        print(f"  {dt.strftime('%Y-%m')}  {mr:+6.1%}   {bal:>12,.0f}원")
    print(f"  합계 {bal/cap_won-1:+.1%}")


if __name__ == "__main__":
    main()

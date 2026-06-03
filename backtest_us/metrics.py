"""Equity-curve metrics for daily strategies — Sharpe / Sortino / MDD / Calmar.

Evaluation axis is risk-adjusted (per philosophy: 안정적 우상향 > raw PnL).
Always reported side-by-side with the benchmark (QQQ buy & hold).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _curve_stats(eq: pd.Series, name: str) -> dict:
    eq = eq.dropna()
    rets = eq.pct_change().dropna()
    n_days = (eq.index[-1] - eq.index[0]).days
    years = n_days / 365.25 if n_days > 0 else np.nan

    total_return = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years and years > 0 else np.nan

    vol = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = rets.mean() / rets.std() * np.sqrt(TRADING_DAYS) if rets.std() > 0 else np.nan
    downside = rets[rets < 0].std()
    sortino = rets.mean() / downside * np.sqrt(TRADING_DAYS) if downside and downside > 0 else np.nan

    peak = eq.cummax()
    dd = eq / peak - 1
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd < 0 and not np.isnan(cagr) else np.nan

    return {
        "name": name,
        "total_return": total_return,
        "cagr": cagr,
        "ann_vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd": float(mdd),
        "calmar": calmar,
        "final_equity": float(eq.iloc[-1]),
    }


def compute_metrics(result, name: str = "strategy") -> list[dict]:
    """Return [strategy, QQQ, EW-universe] stats for side-by-side reporting.

    The EW-universe column is the survivorship-bias control: it shares the
    strategy's exact (survivor) universe, so strategy-minus-EW is the alpha
    that is NOT explained by the universe's hindsight selection.
    """
    strat = _curve_stats(result.equity_curve, name)
    bench = _curve_stats(result.benchmark_curve, "QQQ buy&hold")
    # Rebalance/regime diagnostics on the strategy row.
    if getattr(result, "rebalances", None):
        rbs = result.rebalances
        strat["n_rebalances"] = len(rbs)
        strat["pct_invested"] = np.mean([r.regime_on for r in rbs]) if rbs else 0.0
        turns = [r.turnover for r in rbs if r.turnover > 0]
        strat["avg_turnover"] = float(np.mean(turns)) if turns else 0.0
    out = [strat, bench]
    if getattr(result, "ew_universe_curve", None) is not None:
        out.append(_curve_stats(result.ew_universe_curve, "EW-universe"))
    return out


def format_report(stats_list: list[dict]) -> str:
    rows = [
        ("총수익률", "total_return", "{:.1%}"),
        ("CAGR", "cagr", "{:.1%}"),
        ("연변동성", "ann_vol", "{:.1%}"),
        ("Sharpe", "sharpe", "{:.2f}"),
        ("Sortino", "sortino", "{:.2f}"),
        ("MDD", "mdd", "{:.1%}"),
        ("Calmar", "calmar", "{:.2f}"),
        ("최종자본", "final_equity", "${:,.0f}"),
        ("리밸런스 횟수", "n_rebalances", "{:.0f}"),
        ("투자비중(레짐ON)", "pct_invested", "{:.0%}"),
        ("평균 회전율", "avg_turnover", "{:.0%}"),
    ]
    cols = [s["name"] for s in stats_list]
    wl, wc = 18, 18
    out = [" " * wl + "".join(f"{c:>{wc}}" for c in cols),
           "-" * (wl + wc * len(cols))]
    for label, key, fmt in rows:
        line = f"{label:<{wl}}"
        for s in stats_list:
            v = s.get(key)
            if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                cell = "-"
            else:
                try:
                    cell = fmt.format(v)
                except Exception:
                    cell = str(v)
            line += f"{cell:>{wc}}"
        out.append(line)
    return "\n".join(out)

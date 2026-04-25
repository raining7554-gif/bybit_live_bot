"""Backtest performance metrics."""
from __future__ import annotations
from typing import List
import numpy as np
import pandas as pd


def compute_metrics(result: dict, name: str = "") -> dict:
    trades = result["trades"]
    eq = result["equity_curve"]
    if len(trades) == 0:
        return {"name": name, "n_trades": 0, "final_equity": float(eq.iloc[-1])}

    pnls = np.array([t.pnl for t in trades])
    pnl_pcts = np.array([t.pnl_pct for t in trades])
    wins = pnls > 0
    n = len(pnls)

    win_rate = wins.mean()
    avg_win = pnls[wins].mean() if wins.any() else 0.0
    avg_loss = pnls[~wins].mean() if (~wins).any() else 0.0
    profit_factor = (pnls[wins].sum() / abs(pnls[~wins].sum())) if (~wins).any() and pnls[~wins].sum() != 0 else float("inf")
    expectancy = pnls.mean()

    # Equity-curve based metrics
    eq_v = eq.values
    rets = pd.Series(eq_v).pct_change().fillna(0)
    bars_per_year = 365 * 24 * 4   # 15m bars per year
    sharpe = (rets.mean() / rets.std() * np.sqrt(bars_per_year)) if rets.std() > 0 else 0.0
    downside = rets[rets < 0].std()
    sortino = (rets.mean() / downside * np.sqrt(bars_per_year)) if downside > 0 else 0.0

    peak = np.maximum.accumulate(eq_v)
    dd = (eq_v - peak) / peak
    mdd_pct = float(dd.min())
    mdd_dollar = float((eq_v - peak).min())

    total_return = (eq_v[-1] - eq_v[0]) / eq_v[0]
    days = (eq.index[-1] - eq.index[0]).total_seconds() / 86400
    cagr = (eq_v[-1] / eq_v[0]) ** (365 / days) - 1 if days > 0 and eq_v[-1] > 0 else 0
    calmar = cagr / abs(mdd_pct) if mdd_pct < 0 else float("inf")

    # Consecutive losses
    max_consec_loss = 0
    cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    # Long vs short breakdown
    longs = [t for t in trades if t.side == "long"]
    shorts = [t for t in trades if t.side == "short"]
    long_pnl = sum(t.pnl for t in longs)
    short_pnl = sum(t.pnl for t in shorts)
    long_wr = sum(1 for t in longs if t.pnl > 0) / len(longs) if longs else 0
    short_wr = sum(1 for t in shorts if t.pnl > 0) / len(shorts) if shorts else 0

    # Avg holding period
    avg_bars = np.mean([t.bars for t in trades])

    return {
        "name": name,
        "n_trades": n,
        "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe, "sortino": sortino,
        "mdd_pct": mdd_pct, "mdd_dollar": mdd_dollar,
        "calmar": calmar,
        "max_consec_loss": max_consec_loss,
        "n_long": len(longs), "n_short": len(shorts),
        "long_pnl": long_pnl, "short_pnl": short_pnl,
        "long_wr": long_wr, "short_wr": short_wr,
        "avg_bars": avg_bars,
        "fees_total": sum(t.fees for t in trades),
        "final_equity": float(eq.iloc[-1]),
        "initial_equity": float(eq.iloc[0]),
    }


def format_report(metrics_list: List[dict]) -> str:
    """Side-by-side comparison table."""
    if not metrics_list:
        return "(no results)"
    cols = [m["name"] for m in metrics_list]
    rows = [
        ("거래수", "n_trades", "{:.0f}"),
        ("승률", "win_rate", "{:.1%}"),
        ("Profit Factor", "profit_factor", "{:.2f}"),
        ("기댓값/거래", "expectancy", "${:.2f}"),
        ("총수익률", "total_return", "{:.1%}"),
        ("CAGR", "cagr", "{:.1%}"),
        ("Sharpe", "sharpe", "{:.2f}"),
        ("Sortino", "sortino", "{:.2f}"),
        ("MDD %", "mdd_pct", "{:.1%}"),
        ("MDD $", "mdd_dollar", "${:.2f}"),
        ("Calmar", "calmar", "{:.2f}"),
        ("최대 연속 손실", "max_consec_loss", "{:.0f}"),
        ("롱 거래", "n_long", "{:.0f}"),
        ("숏 거래", "n_short", "{:.0f}"),
        ("롱 승률", "long_wr", "{:.1%}"),
        ("숏 승률", "short_wr", "{:.1%}"),
        ("롱 PnL", "long_pnl", "${:.2f}"),
        ("숏 PnL", "short_pnl", "${:.2f}"),
        ("평균 보유봉", "avg_bars", "{:.1f}"),
        ("총 수수료", "fees_total", "${:.2f}"),
        ("최종 자본", "final_equity", "${:.2f}"),
    ]
    width_label = 18
    width_col = 16
    out = []
    out.append(" " * width_label + "".join(f"{c:>{width_col}}" for c in cols))
    out.append("-" * (width_label + width_col * len(cols)))
    for label, key, fmt in rows:
        line = f"{label:<{width_label}}"
        for m in metrics_list:
            v = m.get(key)
            if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                cell = "-"
            else:
                try:
                    cell = fmt.format(v)
                except Exception:
                    cell = str(v)
            line += f"{cell:>{width_col}}"
        out.append(line)
    return "\n".join(out)

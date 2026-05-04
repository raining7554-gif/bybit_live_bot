"""Sweep over (mid_trail, high_trail) ATR multipliers and compare metrics.

Compares trail-width hypotheses on the same data:
  - tight   (mid 2.0, high 2.5)
  - current (mid 2.5, high 3.0)
  - wide    (mid 3.0, high 4.0)
  - wider   (mid 3.5, high 5.0)

For each combo, runs Strategy D on cached BTC data and prints:
  trades, win%, total return, MDD, Sharpe, fees as % of pnl, avg bars per trade

Usage:
    python -m backtest.sweep_trail            # uses cached data, fetches if missing
    python -m backtest.sweep_trail --days 365
"""
from __future__ import annotations
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

from .data import load_kline
from .indicators import add_all_15m, add_basic_1h, add_basic_4h, sma
from .engine import run_backtest, BTConfig
from .metrics import compute_metrics
from .strategies import strategy_d as sd


COMBOS = [
    ("tight",   2.0, 2.5),
    ("current", 2.5, 3.0),
    ("wide",    3.0, 4.0),
    ("wider",   3.5, 5.0),
    ("widest",  4.0, 6.0),
]


def prepare(symbol: str, days: int, refresh: bool):
    print(f"[sweep] loading {symbol} {days}d ...", flush=True)
    df15 = load_kline(symbol, "15", days=days, refresh=refresh)
    df1h = load_kline(symbol, "60", days=days, refresh=refresh)
    df4h = load_kline(symbol, "240", days=days, refresh=refresh)
    df1d = load_kline(symbol, "D", days=days + 60, refresh=refresh)
    if any(len(d) == 0 for d in [df15, df1h, df4h, df1d]):
        raise RuntimeError("empty data")
    print(f"[sweep] computing indicators ...", flush=True)
    d15 = add_all_15m(df15)
    d1h = add_basic_1h(df1h)
    d4h = add_basic_4h(df4h)
    d1d = df1d.copy()
    d1d["ema50"] = sma(d1d["close"], 50)
    d1d["ema50_prev5"] = d1d["ema50"].shift(5)
    return d15, d1h, d4h, d1d


def trade_breakdown(trades) -> dict:
    """Return reason-distribution + tier-distribution + fee burden."""
    if not trades:
        return {}
    n = len(trades)
    by_reason = {}
    fees_total = sum(t.fees for t in trades)
    pnl_total = sum(t.pnl for t in trades)
    avg_bars = np.mean([t.bars for t in trades])
    for t in trades:
        by_reason[t.reason] = by_reason.get(t.reason, 0) + 1
    return {
        "n": n,
        "fees_pct_of_gross": fees_total / max(abs(pnl_total) + fees_total, 1e-9),
        "avg_bars": avg_bars,
        "reasons": by_reason,
    }


def run_one(label: str, mid: float, high: float, d15, d1h, d4h, d1d, equity: float):
    sd.ATR_TRAIL_MID = mid
    sd.ATR_TRAIL_HIGH = high
    cfg = BTConfig(initial_equity=equity, max_leverage=5.5,
                   use_risk_sizing=False)
    t0 = time.time()
    res = run_backtest(d15, sd.make_strategy(), cfg=cfg,
                       df_1h=d1h, df_4h=d4h, df_1d=d1d, warmup=300)
    m = compute_metrics(res, name=f"{label} (mid={mid} hi={high})")
    bd = trade_breakdown(res["trades"])
    elapsed = time.time() - t0
    print(f"[sweep] {label:8s} mid={mid:.1f} hi={high:.1f} "
          f"-> {bd.get('n', 0)} trades final ${m['final_equity']:.2f} "
          f"({elapsed:.1f}s)", flush=True)
    return m, bd, res["trades"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--equity", type=float, default=1000.0)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()

    d15, d1h, d4h, d1d = prepare(args.symbol, args.days, args.refresh)

    rows = []
    for label, mid, high in COMBOS:
        m, bd, trades = run_one(label, mid, high, d15, d1h, d4h, d1d, args.equity)
        rows.append({
            "label": label,
            "mid": mid,
            "high": high,
            "n_trades": bd.get("n", 0),
            "win_pct": m.get("win_rate", 0),
            "total_return": m.get("total_return", 0),
            "mdd_pct": m.get("mdd_pct", 0),
            "sharpe": m.get("sharpe", 0),
            "calmar": m.get("calmar", 0),
            "profit_factor": m.get("profit_factor", 0),
            "avg_bars": bd.get("avg_bars", 0),
            "fees_pct": bd.get("fees_pct_of_gross", 0),
            "final_equity": m.get("final_equity", 0),
            "reasons": bd.get("reasons", {}),
        })

    print("\n" + "=" * 96)
    print(f" {args.symbol} | {args.days}일 | 초기자본 ${args.equity}")
    print(" Strategy D — trail-width sweep")
    print("=" * 96)
    hdr = (f"{'label':<8} {'mid':>5} {'hi':>5} {'trades':>7} {'win%':>6} "
           f"{'ret%':>8} {'MDD%':>7} {'Sharpe':>7} {'Calmar':>7} "
           f"{'PF':>5} {'avgBar':>7} {'fee%':>6} {'final$':>10}")
    print(hdr)
    print("-" * 96)
    for r in rows:
        print(f"{r['label']:<8} {r['mid']:>5.1f} {r['high']:>5.1f} "
              f"{r['n_trades']:>7d} {r['win_pct']*100:>5.1f}% "
              f"{r['total_return']*100:>7.1f}% {r['mdd_pct']*100:>6.1f}% "
              f"{r['sharpe']:>7.2f} {r['calmar']:>7.2f} "
              f"{r['profit_factor']:>5.2f} {r['avg_bars']:>7.1f} "
              f"{r['fees_pct']*100:>5.1f}% ${r['final_equity']:>9,.2f}")
    print("=" * 96)

    print("\n청산 사유 분포:")
    for r in rows:
        rs = r["reasons"]
        total = sum(rs.values()) or 1
        parts = " ".join(f"{k}={v}({v*100/total:.0f}%)" for k, v in sorted(rs.items()))
        print(f"  {r['label']:<8}: {parts}")

    # Auto verdict
    print("\n자동 판정:")
    best_ret = max(rows, key=lambda r: r["total_return"])
    best_sharpe = max(rows, key=lambda r: r["sharpe"])
    best_calmar = max(rows, key=lambda r: r["calmar"])
    print(f"  최대 수익     : {best_ret['label']:<8} (ret {best_ret['total_return']*100:+.1f}%)")
    print(f"  최대 Sharpe   : {best_sharpe['label']:<8} (Sharpe {best_sharpe['sharpe']:.2f})")
    print(f"  최대 Calmar   : {best_calmar['label']:<8} (Calmar {best_calmar['calmar']:.2f})")
    cur = next(r for r in rows if r["label"] == "current")
    print(f"\n현재 (mid 2.5 / hi 3.0) 대비:")
    for r in rows:
        if r["label"] == "current":
            continue
        d_ret = (r["total_return"] - cur["total_return"]) * 100
        d_sh = r["sharpe"] - cur["sharpe"]
        d_mdd = (r["mdd_pct"] - cur["mdd_pct"]) * 100
        sign_ret = "+" if d_ret >= 0 else ""
        sign_sh = "+" if d_sh >= 0 else ""
        sign_mdd = "+" if d_mdd >= 0 else ""
        print(f"  {r['label']:<8}: ret {sign_ret}{d_ret:.1f}%pt | "
              f"Sharpe {sign_sh}{d_sh:.2f} | MDD {sign_mdd}{d_mdd:.1f}%pt")


if __name__ == "__main__":
    main()

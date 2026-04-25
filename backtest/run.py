"""Backtest runner: download data, run all strategies, print comparative report.

Usage:
    cd /home/user/bybit_live_bot
    python -m backtest.run                 # uses cached data, fetches if missing
    python -m backtest.run --refresh       # force re-download
    python -m backtest.run --days 180      # shorter window
    python -m backtest.run --symbol BTCUSDT --equity 1000

Output:
    - Console report (side-by-side comparison)
    - backtest/reports/<symbol>_<timestamp>.txt
    - backtest/reports/<symbol>_trades.csv (per-strategy trade ledger)
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

from .data import load_kline, load_funding
from .indicators import add_all_15m, add_basic_1h, add_basic_4h, ema, sma, atr as atr_fn
from .engine import run_backtest, BTConfig
from .metrics import compute_metrics, format_report
from .strategies.v63d import make_strategy as make_v63d
from .strategies.strategy_a import make_strategy as make_a
from .strategies.strategy_c import make_strategy as make_c
from .strategies.funding import analyze_funding, format_funding_report


REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def prepare_data(symbol: str, days: int, refresh: bool):
    print(f"[run] Loading data for {symbol} ({days}d) ...")
    df_15m_raw = load_kline(symbol, "15", days=days, refresh=refresh)
    df_1h_raw = load_kline(symbol, "60", days=days, refresh=refresh)
    df_4h_raw = load_kline(symbol, "240", days=days, refresh=refresh)
    df_1d_raw = load_kline(symbol, "D", days=days + 60, refresh=refresh)  # need extra for 50d SMA

    if any(len(d) == 0 for d in [df_15m_raw, df_1h_raw, df_4h_raw, df_1d_raw]):
        raise RuntimeError("Empty dataset — check API connectivity / cache")

    print(f"[run] Computing indicators ...")
    df_15m = add_all_15m(df_15m_raw)
    df_1h = add_basic_1h(df_1h_raw)
    df_4h = add_basic_4h(df_4h_raw)

    # 1d for v6.3d daily-bearish filter: include EMA50 5-bar lag
    df_1d = df_1d_raw.copy()
    df_1d["ema50"] = sma(df_1d["close"], 50)
    df_1d["ema50_prev5"] = df_1d["ema50"].shift(5)

    return df_15m, df_1h, df_4h, df_1d


def run_one(name: str, factory, df_15m, df_1h, df_4h, df_1d, cfg: BTConfig, **kwargs):
    print(f"[run] Backtesting {name} ...")
    t0 = time.time()
    strat = factory()
    res = run_backtest(df_15m, strat, cfg=cfg,
                       df_1h=df_1h, df_4h=df_4h, df_1d=df_1d, warmup=300)
    m = compute_metrics(res, name=name)
    elapsed = time.time() - t0
    print(f"[run] {name}: {m.get('n_trades',0)} trades | final ${m['final_equity']:.2f} | {elapsed:.1f}s")
    return res, m


def save_trades(symbol: str, results: dict[str, dict]):
    rows = []
    for name, res in results.items():
        for t in res["trades"]:
            rows.append({
                "strategy": name,
                "entry_dt": t.entry_dt, "exit_dt": t.exit_dt,
                "side": t.side, "entry": t.entry, "exit": t.exit,
                "size": t.size, "leverage": t.leverage,
                "pnl": t.pnl, "pnl_pct": t.pnl_pct,
                "fees": t.fees, "reason": t.reason, "tag": t.tag, "bars": t.bars,
            })
    if rows:
        df = pd.DataFrame(rows)
        path = os.path.join(REPORT_DIR, f"{symbol}_trades.csv")
        df.to_csv(path, index=False)
        print(f"[run] Trades saved: {path}")


def save_report(symbol: str, days: int, equity: float, table: str, funding_report: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"{symbol}_{ts}.txt")
    header = (
        f"========================================\n"
        f" Bybit Bot Strategy Backtest Report\n"
        f"========================================\n"
        f"Symbol: {symbol} | Days: {days} | Initial Equity: ${equity:.2f}\n"
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n"
        f"========================================\n\n"
    )
    body = table + "\n\n" + funding_report + "\n"
    with open(path, "w") as f:
        f.write(header + body)
    print(f"[run] Report saved: {path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--equity", type=float, default=1000.0)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--strategies", default="v63d,A,C",
                   help="comma-separated: v63d,A,C  (or 'all')")
    p.add_argument("--skip-funding", action="store_true")
    args = p.parse_args()

    df_15m, df_1h, df_4h, df_1d = prepare_data(args.symbol, args.days, args.refresh)

    # Strategy A & C use risk-based sizing (1% / 0.5% per trade); v6.3d uses size_pct fallback
    cfg_risk1 = BTConfig(initial_equity=args.equity, max_leverage=5.0,
                         risk_per_trade=0.01, use_risk_sizing=True)
    cfg_risk_half = BTConfig(initial_equity=args.equity, max_leverage=3.0,
                             risk_per_trade=0.005, use_risk_sizing=True)
    cfg_v63d = BTConfig(initial_equity=args.equity, max_leverage=7.0,
                        risk_per_trade=0.02, use_risk_sizing=False)

    enabled = args.strategies.split(",") if args.strategies != "all" else ["v63d", "A", "C"]
    enabled = [s.strip() for s in enabled]

    metrics_list = []
    results = {}

    if "v63d" in enabled:
        res, m = run_one("v6.3d (현재)", make_v63d, df_15m, df_1h, df_4h, df_1d, cfg_v63d)
        results["v63d"] = res; metrics_list.append(m)
    if "A" in enabled:
        res, m = run_one("A (1H 구조)", make_a, df_15m, df_1h, df_4h, df_1d, cfg_risk1)
        results["A"] = res; metrics_list.append(m)
    if "C" in enabled:
        res, m = run_one("C (15m 돌파)", make_c, df_15m, df_1h, df_4h, df_1d, cfg_risk_half)
        results["C"] = res; metrics_list.append(m)

    table = format_report(metrics_list)
    print("\n" + "=" * 80)
    print(f" {args.symbol} | {args.days}일 | 초기자본 ${args.equity}")
    print("=" * 80)
    print(table)
    print()

    funding_report = ""
    if not args.skip_funding:
        try:
            print("[run] Fetching funding history ...")
            df_fund = load_funding(args.symbol, days=args.days, refresh=args.refresh)
            fr = analyze_funding(df_fund)
            funding_report = format_funding_report(fr)
            print(funding_report)
        except Exception as e:
            funding_report = f"⚠️ Funding analysis failed: {e}"
            print(funding_report)

    save_trades(args.symbol, results)
    save_report(args.symbol, args.days, args.equity, table, funding_report)

    # Quick verdict
    print("\n" + "=" * 80)
    print(" 자동 평가")
    print("=" * 80)
    for m in metrics_list:
        verdict = []
        sh = m.get("sharpe", 0)
        ca = m.get("calmar", 0)
        mdd = m.get("mdd_pct", 0)
        ret = m.get("total_return", 0)
        if sh < 0.3: verdict.append("❌ Sharpe 매우 낮음")
        elif sh < 1.0: verdict.append("⚠️ Sharpe 낮음")
        elif sh < 2.0: verdict.append("✅ Sharpe 양호")
        else: verdict.append("🌟 Sharpe 우수")
        if mdd < -0.30: verdict.append("❌ MDD 심각 (-30%↑)")
        elif mdd < -0.20: verdict.append("⚠️ MDD 큼")
        elif mdd < -0.10: verdict.append("✅ MDD 양호")
        else: verdict.append("🌟 MDD 작음")
        if ret < 0: verdict.append("❌ 손실")
        elif ret < 0.10: verdict.append("⚠️ 수익 미미")
        else: verdict.append(f"✅ 수익 +{ret*100:.0f}%")
        print(f"  [{m['name']}] {' / '.join(verdict)}")


if __name__ == "__main__":
    main()

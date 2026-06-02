"""Backtest runner for the NASDAQ Clenow momentum alpha.

Usage (on your Mac, network enabled):
    python -m backtest_us.run                 # use cached CSVs, fetch if missing
    python -m backtest_us.run --refresh       # force re-download from stooq
    python -m backtest_us.run --top-n 15 --lookback 90

In-container / no-network engine check:
    python -m backtest_us.run --synthetic     # GBM data, verifies mechanics

Output: console report + backtest_us/reports/<timestamp>.txt
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime

from .universe import UNIVERSE, BENCHMARK
from .data import load_prices, make_synthetic_prices
from .alpha_momentum import MomentumConfig, make_alpha
from .engine import BTConfig, run_portfolio_backtest
from .metrics import compute_metrics, format_report

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="force re-download from stooq")
    ap.add_argument("--synthetic", action="store_true", help="use GBM synthetic data (no network)")
    ap.add_argument("--top-n", type=int, default=12)
    ap.add_argument("--lookback", type=int, default=90)
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--cost", type=float, default=0.0010)
    args = ap.parse_args()

    tickers = UNIVERSE
    if args.synthetic:
        print("[run] SYNTHETIC mode — GBM data, engine mechanics check only.")
        allp = make_synthetic_prices(tickers + [BENCHMARK])
        benchmark = allp.pop(BENCHMARK)
        prices = allp
    else:
        print(f"[run] loading {len(tickers)} tickers + {BENCHMARK} from stooq cache "
              f"(refresh={args.refresh}) ...")
        prices = load_prices(tickers, refresh=args.refresh)
        bench = load_prices([BENCHMARK], refresh=args.refresh)
        if BENCHMARK not in bench:
            raise SystemExit(f"benchmark {BENCHMARK} unavailable — cannot run regime filter.")
        benchmark = bench[BENCHMARK]
        if not prices:
            raise SystemExit("no price data — run on a network-enabled machine first "
                             "(stooq is blocked in the web sandbox).")

    mcfg = MomentumConfig(lookback=args.lookback, top_n=args.top_n)
    alpha = make_alpha(mcfg)
    btcfg = BTConfig(initial_equity=args.equity, cost=args.cost)

    result = run_portfolio_backtest(prices, benchmark, alpha, btcfg)
    stats = compute_metrics(result, name=f"Clenow top{args.top_n}")
    report = format_report(stats)

    header = (f"NASDAQ Clenow Momentum — {len(prices)} stocks, "
              f"lookback={args.lookback}, top_n={args.top_n}, cost={args.cost:.2%}\n"
              f"period: {result.equity_curve.index[0].date()} .. "
              f"{result.equity_curve.index[-1].date()}\n")
    print("\n" + header)
    print(report)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "synthetic" if args.synthetic else "stooq"
    path = os.path.join(REPORT_DIR, f"{tag}_{ts}.txt")
    with open(path, "w") as f:
        f.write(header + "\n" + report + "\n")
    print(f"\n[run] report saved: {path}")


if __name__ == "__main__":
    main()

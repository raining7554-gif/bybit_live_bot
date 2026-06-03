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
from .pit_universe import load_pit_universe, PIT_BENCHMARK
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
    ap.add_argument("--pit", action="store_true",
                    help="point-in-time S&P500 universe (survivorship-bias free)")
    ap.add_argument("--top-n", type=int, default=12)
    ap.add_argument("--lookback", type=int, default=90)
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--cost", type=float, default=0.0010)
    args = ap.parse_args()

    eligibility = None
    benchmark_sym = BENCHMARK
    if args.pit:
        tickers, eligibility = load_pit_universe(refresh=args.refresh)
        benchmark_sym = PIT_BENCHMARK
        ended = sum(1 for _, e in eligibility.values() if e is not None)
        print(f"[run] PIT mode — {len(tickers)} S&P500 names "
              f"({ended} removed/delisted, {len(tickers)-ended} current), bench={benchmark_sym}")
    else:
        tickers = UNIVERSE

    if args.synthetic:
        print("[run] SYNTHETIC mode — GBM data, engine mechanics check only.")
        allp = make_synthetic_prices(tickers + [benchmark_sym])
        benchmark = allp.pop(benchmark_sym)
        prices = allp
    else:
        print(f"[run] loading {len(tickers)} tickers + {benchmark_sym} "
              f"(refresh={args.refresh}) ...")
        prices = load_prices(tickers, refresh=args.refresh)
        bench = load_prices([benchmark_sym], refresh=args.refresh)
        if benchmark_sym not in bench:
            raise SystemExit(f"benchmark {benchmark_sym} unavailable — cannot run regime filter.")
        benchmark = bench[benchmark_sym]
        if not prices:
            raise SystemExit("no price data — run on a network-enabled machine first "
                             "(stooq is blocked in the web sandbox).")
        if args.pit:
            cov = len(prices) / len(tickers) if tickers else 0
            ended_got = sum(1 for t in prices if eligibility.get(t, (None, None))[1] is not None)
            print(f"[run] PIT price coverage: {len(prices)}/{len(tickers)} ({cov:.0%}); "
                  f"delisted names fetched: {ended_got}")

    mcfg = MomentumConfig(lookback=args.lookback, top_n=args.top_n)
    alpha = make_alpha(mcfg)
    btcfg = BTConfig(initial_equity=args.equity, cost=args.cost)

    result = run_portfolio_backtest(prices, benchmark, alpha, btcfg, eligibility=eligibility)
    stats = compute_metrics(result, name=f"Clenow top{args.top_n}", bench_name=benchmark_sym)
    report = format_report(stats)

    uni = "S&P500 point-in-time" if args.pit else "NASDAQ survivor"
    header = (f"Clenow Momentum [{uni}] — {len(prices)} stocks, "
              f"lookback={args.lookback}, top_n={args.top_n}, cost={args.cost:.2%}\n"
              f"period: {result.equity_curve.index[0].date()} .. "
              f"{result.equity_curve.index[-1].date()}\n")
    print("\n" + header)
    print(report)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "synthetic" if args.synthetic else ("pit" if args.pit else "stooq")
    path = os.path.join(REPORT_DIR, f"{tag}_{ts}.txt")
    with open(path, "w") as f:
        f.write(header + "\n" + report + "\n")
    print(f"\n[run] report saved: {path}")


if __name__ == "__main__":
    main()

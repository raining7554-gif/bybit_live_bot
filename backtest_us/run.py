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
from .data import load_prices, make_synthetic_prices, export_bundle, load_bundle
from .alpha_momentum import MomentumConfig, make_alpha
from .engine import BTConfig, run_portfolio_backtest
from .metrics import compute_metrics, format_report, _curve_stats

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORT_DIR, exist_ok=True)

# Curated momentum designs to test whether ANY beats the EW baseline. Hypothesis:
# the top-12 concentration is what sinks Sharpe — more names + classic 12-1 period
# (longer lookback, skip the recent month) should keep the regime drawdown control
# while raising risk-adjusted return toward/above EW.
_SWEEP = [
    ("lb90  top12 skip0   (current)", dict(lookback=90,  top_n=12, skip=0)),
    ("lb90  top30 skip0",             dict(lookback=90,  top_n=30, skip=0)),
    ("lb90  top50 skip0",             dict(lookback=90,  top_n=50, skip=0)),
    ("lb126 top30 skip21",            dict(lookback=126, top_n=30, skip=21)),
    ("lb126 top50 skip21",            dict(lookback=126, top_n=50, skip=21)),
    ("lb252 top30 skip21",            dict(lookback=252, top_n=30, skip=21)),
    ("lb252 top50 skip21",            dict(lookback=252, top_n=50, skip=21)),
    ("lb252 top50 skip21 eqwt",       dict(lookback=252, top_n=50, skip=21, weighting="equal")),
]


def run_sweep(prices, benchmark, btcfg, eligibility, bench_sym, is_pit):
    """Run several momentum designs on one dataset; compare each to the EW baseline."""
    rows = []
    ew_row = bench_row = None
    for label, kw in _SWEEP:
        alpha = make_alpha(MomentumConfig(**kw))
        res = run_portfolio_backtest(prices, benchmark, alpha, btcfg, eligibility=eligibility)
        rows.append((label, _curve_stats(res.equity_curve, label)))
        if ew_row is None:  # identical across configs — capture once
            ew_row = _curve_stats(res.ew_universe_curve, "EW-universe (baseline)")
            bench_row = _curve_stats(res.benchmark_curve, f"{bench_sym} buy&hold")

    uni = "S&P500 point-in-time" if is_pit else "NASDAQ survivor"
    hdr = f"Momentum design sweep [{uni}] — {len(prices)} stocks, cost={btcfg.cost:.2%}"
    cols = ["CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Calmar"]
    keys = ["cagr", "ann_vol", "sharpe", "sortino", "mdd", "calmar"]

    def fmt(st):
        def g(k):
            v = st[k]
            if k in ("cagr", "ann_vol", "mdd"):
                return f"{v:+.1%}" if v == v else "  n/a"
            return f"{v:.2f}" if v == v else " n/a"
        return "  ".join(f"{g(k):>7}" for k in keys)

    ew_sh = ew_row["sharpe"]
    lines = [hdr, "", f"{'design':<32}" + "  ".join(f"{c:>7}" for c in cols) + "   vs EW",
             "-" * 92]
    for label, st in rows:
        flag = "WIN " if st["sharpe"] > ew_sh else "lose"
        lines.append(f"{label:<32}{fmt(st)}   {flag} ({st['sharpe']-ew_sh:+.2f})")
    lines.append("-" * 92)
    lines.append(f"{ew_row['name']:<32}{fmt(ew_row)}")
    lines.append(f"{bench_row['name']:<32}{fmt(bench_row)}")
    report = "\n".join(lines)
    print("\n" + report)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "sweep_pit" if is_pit else "sweep"
    path = os.path.join(REPORT_DIR, f"{tag}_{ts}.txt")
    with open(path, "w") as f:
        f.write(report + "\n")
    print(f"\n[run] sweep saved: {path}")


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
    ap.add_argument("--sweep", action="store_true",
                    help="momentum design sweep vs EW baseline (lookback/top_n/skip)")
    ap.add_argument("--export-bundle", action="store_true",
                    help="write a committed close-price bundle for the offline sandbox")
    ap.add_argument("--bundle", action="store_true",
                    help="load prices from the committed research bundle (no network)")
    args = ap.parse_args()

    # --bundle implies the PIT universe (the bundle is built from PIT prices).
    use_pit = args.pit or args.bundle
    eligibility = None
    benchmark_sym = BENCHMARK
    if use_pit:
        tickers, eligibility = load_pit_universe(refresh=args.refresh and not args.bundle)
        benchmark_sym = PIT_BENCHMARK
        ended = sum(1 for _, e in eligibility.values() if e is not None)
        print(f"[run] PIT mode — {len(tickers)} S&P500 names "
              f"({ended} removed/delisted, {len(tickers)-ended} current), bench={benchmark_sym}")
    else:
        tickers = UNIVERSE

    if args.bundle:
        print("[run] BUNDLE mode — loading committed research bundle (offline).")
        prices = load_bundle()
        if benchmark_sym not in prices:
            raise SystemExit(f"benchmark {benchmark_sym} missing from bundle.")
        benchmark = prices.pop(benchmark_sym)
        cov = len(prices) / len(tickers) if tickers else 0
        ended_got = sum(1 for t in prices if eligibility.get(t, (None, None))[1] is not None)
        print(f"[run] bundle coverage: {len(prices)}/{len(tickers)} ({cov:.0%}); "
              f"delisted fetched: {ended_got}")
    elif args.synthetic:
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
        if use_pit:
            cov = len(prices) / len(tickers) if tickers else 0
            ended_got = sum(1 for t in prices if eligibility.get(t, (None, None))[1] is not None)
            print(f"[run] PIT price coverage: {len(prices)}/{len(tickers)} ({cov:.0%}); "
                  f"delisted names fetched: {ended_got}")

    if args.export_bundle:
        path = export_bundle(prices, extra={benchmark_sym: benchmark})
        size_mb = os.path.getsize(path) / 1e6
        print(f"[run] bundle exported: {path} ({size_mb:.1f} MB, "
              f"{len(prices)+1} series incl. {benchmark_sym})")
        return

    btcfg = BTConfig(initial_equity=args.equity, cost=args.cost)

    if args.sweep:
        run_sweep(prices, benchmark, btcfg, eligibility, benchmark_sym, use_pit)
        return

    mcfg = MomentumConfig(lookback=args.lookback, top_n=args.top_n)
    alpha = make_alpha(mcfg)
    result = run_portfolio_backtest(prices, benchmark, alpha, btcfg, eligibility=eligibility)
    stats = compute_metrics(result, name=f"Clenow top{args.top_n}", bench_name=benchmark_sym)
    report = format_report(stats)

    uni = "S&P500 point-in-time" if use_pit else "NASDAQ survivor"
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

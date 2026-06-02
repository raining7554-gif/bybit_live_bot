"""Engine correctness tests — the most important being NO LOOK-AHEAD.

Run: python -m backtest_us.test_engine
"""
from __future__ import annotations

import numpy as np

from .data import make_synthetic_prices
from .alpha_momentum import MomentumConfig, make_alpha
from .engine import BTConfig, run_portfolio_backtest


def _setup(days):
    allp = make_synthetic_prices([f"S{i}" for i in range(20)] + ["QQQ"], days=days)
    bench = allp.pop("QQQ")
    return allp, bench


def test_no_lookahead():
    """Causality: the equity curve up to day K must be IDENTICAL whether or not
    data after K exists. If any future price leaked into a past decision, the
    truncated run would diverge before K."""
    alpha = make_alpha(MomentumConfig(top_n=8))
    cfg = BTConfig()

    full_prices, full_bench = _setup(900)
    full = run_portfolio_backtest(full_prices, full_bench, alpha, cfg)

    K = 600
    trunc_prices = {t: df.iloc[:K] for t, df in full_prices.items()}
    trunc_bench = full_bench.iloc[:K]
    trunc = run_portfolio_backtest(trunc_prices, trunc_bench, alpha, cfg)

    a = full.equity_curve.iloc[:K].values
    b = trunc.equity_curve.values
    # Compare overlapping region (truncated run is length K).
    n = min(len(a), len(b))
    max_diff = np.max(np.abs(a[:n] - b[:n]))
    assert max_diff < 1e-6, f"LOOK-AHEAD LEAK: max equity diff {max_diff:.6g}"
    print(f"[PASS] no_lookahead: equity curves identical up to day {n} (max diff {max_diff:.2e})")


def test_regime_filter_goes_to_cash():
    """When the benchmark is in a downtrend, the book should hold no positions."""
    prices, bench = _setup(700)
    # Force benchmark below its MA for the whole back half by overwriting closes.
    bench = bench.copy()
    half = len(bench) // 2
    bench.iloc[half:, bench.columns.get_loc("close")] = bench["close"].iloc[half] * 0.5
    alpha = make_alpha(MomentumConfig(top_n=8))
    res = run_portfolio_backtest(prices, bench, alpha, BTConfig())
    # Rebalances in the forced-down region must all be regime-off.
    down = [r for r in res.rebalances if r.dt >= bench.index[half + 210]]
    assert down, "no rebalances in down-regime window to check"
    off = [r for r in down if not r.regime_on]
    assert len(off) == len(down), f"regime filter let {len(down)-len(off)} buys through in downtrend"
    print(f"[PASS] regime_filter: all {len(down)} down-regime rebalances went to cash")


def test_costs_reduce_equity():
    """Higher trading cost must not increase final equity (sanity on cost wiring)."""
    prices, bench = _setup(700)
    alpha = make_alpha(MomentumConfig(top_n=8))
    cheap = run_portfolio_backtest(prices, bench, alpha, BTConfig(cost=0.0))
    pricey = run_portfolio_backtest(prices, bench, alpha, BTConfig(cost=0.01))
    assert pricey.final_equity <= cheap.final_equity + 1e-6, "higher cost raised equity?!"
    print(f"[PASS] costs: cost=0 -> ${cheap.final_equity:,.0f}, "
          f"cost=1% -> ${pricey.final_equity:,.0f}")


if __name__ == "__main__":
    test_no_lookahead()
    test_regime_filter_goes_to_cash()
    test_costs_reduce_equity()
    print("\nAll engine tests passed.")

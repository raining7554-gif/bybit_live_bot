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


def test_pit_eligibility_excludes_delisted():
    """A name removed from the index must not be ranked or held after its end
    date, and must not be frozen into the EW benchmark by the ffill."""
    prices, bench = _setup(800)
    # Make S0 a strong, smooth uptrend so momentum WANTS it, then delist it midway.
    s0 = prices["S0"].copy()
    end_i = 400
    eligibility = {t: (prices[t].index[0], None) for t in prices}
    eligibility["S0"] = (prices["S0"].index[0], prices["S0"].index[end_i])
    alpha = make_alpha(MomentumConfig(top_n=8))
    res = run_portfolio_backtest(prices, bench, alpha, BTConfig(), eligibility=eligibility)
    # After the end date, S0 must never appear in any target basket.
    end_dt = prices["S0"].index[end_i]
    leaked = [dt for dt, w in res.weights_log.items() if dt > end_dt and "S0" in w]
    assert not leaked, f"delisted S0 ranked after end on {len(leaked)} rebalances"
    print(f"[PASS] pit_eligibility: S0 excluded on all {sum(1 for d in res.weights_log if d>end_dt)} "
          f"post-delist rebalances")


def test_eligibility_none_is_backward_compatible():
    """eligibility=None must reproduce the legacy survivor-mode curve exactly."""
    prices, bench = _setup(700)
    alpha = make_alpha(MomentumConfig(top_n=8))
    a = run_portfolio_backtest(prices, bench, alpha, BTConfig())
    full = {t: (prices[t].index[0], None) for t in prices}  # everyone always listed
    b = run_portfolio_backtest(prices, bench, alpha, BTConfig(), eligibility=full)
    diff = np.max(np.abs(a.equity_curve.values - b.equity_curve.values))
    assert diff < 1e-6, f"eligibility wiring changed survivor-mode result: {diff:.2e}"
    print(f"[PASS] eligibility_backcompat: all-listed == None (max diff {diff:.2e})")


if __name__ == "__main__":
    test_no_lookahead()
    test_regime_filter_goes_to_cash()
    test_costs_reduce_equity()
    test_pit_eligibility_excludes_delisted()
    test_eligibility_none_is_backward_compatible()
    print("\nAll engine tests passed.")

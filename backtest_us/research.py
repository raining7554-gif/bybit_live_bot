"""Autonomous strategy-research harness (offline, runs off the committed bundle).

Findings so far (ROADMAP [1]-[2c]): Clenow stock-SELECTION is not an alpha — on
both survivor and point-in-time universes a plain equal-weight hold (EW) beats it
on Sharpe. The only robust, design-independent edge is the regime filter's
DRAWDOWN control (MDD roughly halved). So the natural strategy is to stop picking
stocks and instead apply the regime timing to a broad, diversified book.

This module tests that family of ideas against the EW / SPY baselines:
  python -m backtest_us.research

Everything here is survivorship-bias-free (PIT eligibility) and look-ahead-free
(reuses the validated engine). Results are appended to research_log.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pit_universe import load_pit_universe, PIT_BENCHMARK
from .data import load_bundle
from .alpha_momentum import MomentumConfig, make_alpha
from .engine import BTConfig, run_portfolio_backtest
from .metrics import _curve_stats


# ── strategy alpha factories ──────────────────────────────────────────
def alpha_ew_all():
    """Equal weight across every name with a fresh price (regime timing handled
    by the engine). This is 'regime-timed beta': EW exposure, but only while the
    index is in an uptrend."""
    def fn(w: pd.DataFrame) -> list[tuple[str, float]]:
        last = w.iloc[-1]
        names = [t for t in w.columns if last.get(t) == last.get(t)]  # not NaN
        if not names:
            return []
        wt = 1.0 / len(names)
        return [(t, wt) for t in names]
    return fn


def alpha_ew_trend(ma: int = 100, min_history: int = 120):
    """Equal weight across names trading ABOVE their own `ma`-day average (each
    name must be in its own uptrend), on top of the engine's index regime filter."""
    def fn(w: pd.DataFrame) -> list[tuple[str, float]]:
        picks = []
        for t in w.columns:
            s = w[t].dropna()
            if len(s) < min_history:
                continue
            if s.values[-1] > s.values[-ma:].mean():
                picks.append(t)
        if not picks:
            return []
        wt = 1.0 / len(picks)
        return [(t, wt) for t in picks]
    return fn


def alpha_ew_topk_trend(top_k: int = 100, ma: int = 100, lookback: int = 120, min_history: int = 150):
    """Equal weight the top-K names by simple `lookback` return among those above
    their `ma` — diversified momentum (no vol-parity, no concentration)."""
    def fn(w: pd.DataFrame) -> list[tuple[str, float]]:
        scored = []
        for t in w.columns:
            s = w[t].dropna()
            if len(s) < min_history:
                continue
            v = s.values
            if v[-1] <= v[-ma:].mean():
                continue
            ret = v[-1] / v[-lookback] - 1.0
            scored.append((ret, t))
        if not scored:
            return []
        scored.sort(reverse=True)
        picks = [t for _, t in scored[:top_k]]
        wt = 1.0 / len(picks)
        return [(t, wt) for t in picks]
    return fn


# ── runner ────────────────────────────────────────────────────────────
def _run(label, alpha, prices, benchmark, eligibility, regime_ma=200, cost=0.0010):
    cfg = BTConfig(cost=cost, regime_ma=regime_ma, warmup=max(200, regime_ma))
    res = run_portfolio_backtest(prices, benchmark, alpha, cfg, eligibility=eligibility)
    st = _curve_stats(res.equity_curve, label)
    rbs = res.rebalances
    st["pct_inv"] = np.mean([r.regime_on for r in rbs]) if rbs else 0.0
    turns = [r.turnover for r in rbs if r.turnover > 0]
    st["turnover"] = float(np.mean(turns)) if turns else 0.0
    return st, res


def main():
    tickers, eligibility = load_pit_universe()
    prices = load_bundle()
    benchmark = prices.pop(PIT_BENCHMARK)
    print(f"[research] {len(prices)} names from bundle, bench={PIT_BENCHMARK}\n")

    # Baselines (computed once from any run's EW/benchmark curves).
    _, base = _run("EW-all regime200", alpha_ew_all(), prices, benchmark, eligibility)
    ew = _curve_stats(base.ew_universe_curve, "EW-universe (buy&hold)")
    spy = _curve_stats(base.benchmark_curve, f"{PIT_BENCHMARK} buy&hold")
    for d in (ew, spy):
        d["pct_inv"] = d["turnover"] = float("nan")

    strategies = [
        ("EW-all  regime100",        alpha_ew_all(),                 100),
        ("EW-all  regime150",        alpha_ew_all(),                 150),
        ("EW-all  regime200",        alpha_ew_all(),                 200),
        ("EW-trend100 regime200",    alpha_ew_trend(100),            200),
        ("EW-trend200 regime200",    alpha_ew_trend(200),            200),
        ("EWtop100-trend regime200", alpha_ew_topk_trend(100, 100),  200),
        ("EWtop50-trend  regime200", alpha_ew_topk_trend(50, 100),   200),
        ("Clenow top12 (ref)",       make_alpha(MomentumConfig(lookback=90, top_n=12)), 200),
    ]

    rows = []
    for label, alpha, rma in strategies:
        st, _ = _run(label, alpha, prices, benchmark, eligibility, regime_ma=rma)
        rows.append(st)
        print(f"  ran {label:<26} Sharpe={st['sharpe']:.2f} MDD={st['mdd']:+.1%}")

    _print_table(rows + [ew, spy], ew["sharpe"])


def _print_table(rows, ew_sharpe):
    cols = ["CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Calmar", "%inv", "turn"]
    keys = ["cagr", "ann_vol", "sharpe", "sortino", "mdd", "calmar", "pct_inv", "turnover"]

    def cell(st, k):
        v = st.get(k, float("nan"))
        if v != v:
            return "  -"
        if k in ("cagr", "ann_vol", "mdd", "pct_inv", "turnover"):
            return f"{v:+.1%}" if k in ("cagr", "mdd") else f"{v:.0%}"
        return f"{v:.2f}"

    print("\n" + "=" * 100)
    print(f"{'strategy':<28}" + "".join(f"{c:>8}" for c in cols) + "   vs EW")
    print("-" * 100)
    for st in rows:
        line = f"{st['name']:<28}" + "".join(f"{cell(st,k):>8}" for k in keys)
        sh = st["sharpe"]
        if st["name"].startswith(("EW-universe", "SPY")):
            tag = ""
        else:
            tag = f"   {'WIN ' if sh > ew_sharpe else 'lose'} ({sh-ew_sharpe:+.2f})"
        print(line + tag)
    print("=" * 100)


if __name__ == "__main__":
    main()

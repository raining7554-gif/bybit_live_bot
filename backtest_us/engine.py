"""Cross-sectional long-only portfolio backtester (daily bars, weekly rebalance).

No look-ahead, by construction:
  - on a rebalance signal day, the alpha sees closes up to & including that
    day's close (`closes.iloc[: i + 1]`);
  - the resulting target basket is filled at the NEXT session's OPEN.

Positions are held between rebalances and marked-to-market daily at the close.
A regime filter moves the book fully to cash when the benchmark is below its
long moving average.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .data import close_matrix


@dataclass
class BTConfig:
    initial_equity: float = 100_000.0
    cost: float = 0.0010        # per-side fee+slippage on traded notional (10 bps)
    regime_ma: int = 200        # benchmark MA for the on/off regime filter
    rebalance: str = "W"        # weekly rebalance (signal on last trading day of week)
    warmup: int = 200           # skip until enough history for MAs/regime


@dataclass
class Rebalance:
    dt: pd.Timestamp
    regime_on: bool
    n_positions: int
    turnover: float             # traded notional / equity at that rebalance


@dataclass
class BTResult:
    equity_curve: pd.Series
    benchmark_curve: pd.Series
    ew_universe_curve: pd.Series = None   # equal-weight buy&hold of same universe
    rebalances: list[Rebalance] = field(default_factory=list)
    weights_log: dict = field(default_factory=dict)   # dt -> {ticker: weight}
    final_equity: float = 0.0


def _signal_days(index: pd.DatetimeIndex, rule: str) -> set:
    """Last trading day of each period (e.g. each ISO week) within `index`."""
    s = pd.Series(index, index=index)
    last = s.resample(rule).last().dropna()
    return set(last.values)


def run_portfolio_backtest(
    prices: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    alpha_fn: Callable[[pd.DataFrame], list[tuple[str, float]]],
    cfg: BTConfig = BTConfig(),
    eligibility: dict[str, tuple] | None = None,
) -> BTResult:
    """Run the backtest.

    `eligibility`, when given, is the point-in-time membership window per ticker:
    ``{ticker: (start_ts, end_ts_or_None)}``. With it the run is survivorship-bias
    free — a name is only a candidate (and only counts in the EW benchmark) while
    listed, and any holding is liquidated once it leaves the index. Without it the
    legacy survivor-universe behaviour is preserved exactly.
    """
    # Master calendar = benchmark's trading sessions.
    master = benchmark.index
    # `closes` is forward-filled for valuation & execution fills (so a name that
    # delists between rebalances can still be marked / sold at its last price).
    closes = close_matrix(prices).reindex(master).ffill()
    opens = close_matrix(prices, field="open").reindex(master)
    # Fill price for execution: prefer the open; fall back to that day's close.
    fill = opens.where(opens.notna(), closes)

    # `closes_live` masks each name to its listed window (NaN before start / after
    # end). It drives candidate selection and the EW benchmark so that the survivor
    # bias is removed and delisting declines are felt, not frozen by the ffill.
    if eligibility is not None:
        listed = pd.DataFrame(False, index=master, columns=closes.columns)
        for t in closes.columns:
            win = eligibility.get(t)
            if win is None:
                continue
            start, end = win
            mask = master >= start
            if end is not None:
                mask &= master <= end
            listed[t] = mask
        closes_live = closes.where(listed)
    else:
        closes_live = closes

    bench_close = benchmark["close"].reindex(master).ffill()
    bench_ma = bench_close.rolling(cfg.regime_ma).mean()

    sig_days = _signal_days(master, cfg.rebalance)

    cash = cfg.initial_equity
    holdings: dict[str, float] = {}          # ticker -> shares
    equity_curve = np.zeros(len(master))
    pending: list[tuple[str, float]] | None = None

    rebalances: list[Rebalance] = []
    weights_log: dict = {}

    for i, dt in enumerate(master):
        px_fill = fill.loc[dt]

        # 1) Execute the basket decided at the previous signal day, at today's open.
        if pending is not None:
            equity_now = cash + sum(
                sh * closes.at[dt, t] for t, sh in holdings.items()
                if t in closes.columns and not np.isnan(closes.at[dt, t])
            )
            target_shares: dict[str, float] = {}
            for t, w in pending:
                p = px_fill.get(t, np.nan)
                if p is not None and not np.isnan(p) and p > 0:
                    target_shares[t] = (w * equity_now) / p

            traded_notional = 0.0
            for t in set(holdings) | set(target_shares):
                p = px_fill.get(t, np.nan)
                cur_sh = holdings.get(t, 0.0)
                if p is None or np.isnan(p) or p <= 0:
                    continue  # untradeable today; leave position as-is
                tgt_sh = target_shares.get(t, 0.0)
                dsh = tgt_sh - cur_sh
                if abs(dsh) * p < 1e-6:
                    continue
                traded_notional += abs(dsh) * p
                cash -= dsh * p                      # buy reduces cash, sell adds
                cash -= abs(dsh) * p * cfg.cost      # fee + slippage
                if tgt_sh <= 1e-9:
                    holdings.pop(t, None)
                else:
                    holdings[t] = tgt_sh

            rb = rebalances[-1]
            rb.turnover = traded_notional / equity_now if equity_now > 0 else 0.0
            pending = None

        # 2) Mark-to-market at the close.
        equity = cash + sum(
            sh * closes.at[dt, t] for t, sh in holdings.items()
            if t in closes.columns and not np.isnan(closes.at[dt, t])
        )
        equity_curve[i] = equity

        # 3) Generate the next basket at the close of a signal day.
        if i >= cfg.warmup and dt in sig_days and i + 1 < len(master):
            regime_on = bool(bench_close.iloc[i] > bench_ma.iloc[i]) if not np.isnan(bench_ma.iloc[i]) else False
            if regime_on:
                window = closes_live.iloc[: i + 1]   # up to & incl today -> no look-ahead
                if eligibility is not None:
                    # Only names listed *today* are candidates (a delisted name's
                    # stale pre-delist window must not be ranked).
                    live_today = closes_live.columns[closes_live.iloc[i].notna()]
                    window = window[live_today]
                targets = alpha_fn(window)
            else:
                targets = []                    # regime off -> all cash
            pending = targets
            rebalances.append(Rebalance(dt=dt, regime_on=regime_on,
                                        n_positions=len(targets), turnover=0.0))
            weights_log[dt] = dict(targets)

    eq = pd.Series(equity_curve, index=master)
    bench_curve = bench_close / bench_close.iloc[0] * cfg.initial_equity

    # Equal-weight buy&hold of the SAME universe — a survivorship-bias control.
    # Strategy and this benchmark share the identical universe, so the gap between
    # them isolates the alpha (momentum + regime). Under PIT eligibility this EW
    # holds every name *while listed* — including losers into their decline — which
    # is exactly the fair test the survivor universe could not provide.
    daily_ret = closes_live.pct_change()
    # Safety net: cap per-name daily upside at +100% so a single residual data
    # glitch cannot blow up the index. Downside is kept intact — delisting
    # collapses are real and the EW benchmark must feel them.
    daily_ret = daily_ret.clip(upper=1.0)
    ew_ret = daily_ret.mean(axis=1)               # avg across listed names each day
    ew_curve = (1 + ew_ret.fillna(0)).cumprod() * cfg.initial_equity

    return BTResult(
        equity_curve=eq,
        benchmark_curve=bench_curve,
        ew_universe_curve=ew_curve,
        rebalances=rebalances,
        weights_log=weights_log,
        final_equity=float(eq.iloc[-1]),
    )

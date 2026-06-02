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
) -> BTResult:
    # Master calendar = benchmark's trading sessions.
    master = benchmark.index
    closes = close_matrix(prices).reindex(master).ffill()
    opens = close_matrix(prices, field="open").reindex(master)
    # Fill price for execution: prefer the open; fall back to that day's close.
    fill = opens.where(opens.notna(), closes)

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
                window = closes.iloc[: i + 1]   # up to & incl today -> no look-ahead
                targets = alpha_fn(window)
            else:
                targets = []                    # regime off -> all cash
            pending = targets
            rebalances.append(Rebalance(dt=dt, regime_on=regime_on,
                                        n_positions=len(targets), turnover=0.0))
            weights_log[dt] = dict(targets)

    eq = pd.Series(equity_curve, index=master)
    bench_curve = bench_close / bench_close.iloc[0] * cfg.initial_equity
    return BTResult(
        equity_curve=eq,
        benchmark_curve=bench_curve,
        rebalances=rebalances,
        weights_log=weights_log,
        final_equity=float(eq.iloc[-1]),
    )

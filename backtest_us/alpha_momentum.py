"""Clenow cross-sectional momentum alpha ("Stocks on the Move").

Score = annualized slope of an exponential (log-linear) regression of price
over a lookback window, multiplied by R² (penalises noisy/erratic trends).

Selection at each rebalance:
  - rank candidates by score (desc),
  - keep only names trading above their long MA (uptrend confirmation),
  - optionally exclude names with a recent oversized gap (event risk),
  - take the top-N, weight by inverse volatility (vol parity), cap per name.

All computation uses data up to and including the signal day — no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MomentumConfig:
    lookback: int = 90          # regression window (trading days, ~Clenow 90)
    top_n: int = 12             # 소수정예: small concentrated basket
    ma_trend: int = 100         # only hold names above this MA
    vol_window: int = 20        # window for inverse-vol weighting
    max_weight: float = 0.20    # per-name weight cap
    max_gap: float = 0.15       # exclude if any 1-day move in lookback exceeds this
    min_history: int = 120      # need at least this many bars to score


def _annualized_slope_r2(log_prices: np.ndarray) -> tuple[float, float]:
    """Fit log(price) = a + b*t. Return (annualized_return, r2).

    annualized_return = exp(b)**252 - 1.
    """
    n = len(log_prices)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    y_mean = log_prices.mean()
    xd = x - x_mean
    yd = log_prices - y_mean
    denom = (xd * xd).sum()
    if denom == 0:
        return 0.0, 0.0
    slope = (xd * yd).sum() / denom
    # R²
    ss_tot = (yd * yd).sum()
    if ss_tot == 0:
        r2 = 0.0
    else:
        pred = slope * xd
        ss_res = ((yd - pred) ** 2).sum()
        r2 = 1.0 - ss_res / ss_tot
    annualized = float(np.exp(slope) ** 252 - 1.0)
    return annualized, float(r2)


def make_alpha(cfg: MomentumConfig = MomentumConfig()):
    """Return alpha_fn(window_closes) -> list[(ticker, weight)] for the engine.

    `window_closes` is a [date x ticker] close-price DataFrame whose LAST row is
    the signal day. The engine guarantees it contains no future data.
    """

    def alpha_fn(window_closes: pd.DataFrame) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}
        vols: dict[str, float] = {}
        for t in window_closes.columns:
            s = window_closes[t].dropna()
            if len(s) < cfg.min_history:
                continue
            closes = s.values[-cfg.lookback:]
            if len(closes) < cfg.lookback or np.any(closes <= 0):
                continue
            # Trend confirmation: price above long MA.
            ma = s.values[-cfg.ma_trend:].mean() if len(s) >= cfg.ma_trend else None
            if ma is None or closes[-1] <= ma:
                continue
            # Event-risk filter: skip names with an oversized recent gap.
            rets = np.diff(closes) / closes[:-1]
            if np.max(np.abs(rets)) > cfg.max_gap:
                continue
            ann, r2 = _annualized_slope_r2(np.log(closes))
            if ann <= 0:
                continue
            scores[t] = ann * r2
            vol = np.std(rets[-cfg.vol_window:]) if len(rets) >= cfg.vol_window else np.std(rets)
            vols[t] = vol if vol > 0 else np.nan

        if not scores:
            return []
        ranked = sorted(scores, key=scores.get, reverse=True)[: cfg.top_n]

        # Inverse-volatility weights (vol parity), capped and renormalised.
        inv = np.array([1.0 / vols[t] if vols.get(t) and not np.isnan(vols[t]) else 0.0
                        for t in ranked])
        if inv.sum() <= 0:
            inv = np.ones(len(ranked))
        w = inv / inv.sum()
        w = np.minimum(w, cfg.max_weight)
        if w.sum() > 0:
            w = w / w.sum()
        return list(zip(ranked, w))

    return alpha_fn

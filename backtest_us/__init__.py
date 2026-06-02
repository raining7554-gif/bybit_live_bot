"""NASDAQ cross-sectional quant backtest framework.

Separate from `backtest/` (which is single-asset Bybit crypto perps).
This package is long-only, daily-bar, cross-sectional (rank many stocks,
hold top-N, weekly rebalance) — the right shape for equity momentum.

Design principles (per project philosophy):
  - 소수정예: one validated alpha at a time, hold a small top-N basket.
  - 안정적 우상향: evaluate on Sharpe / MDD / Calmar, not raw PnL.
  - 레짐 필터: only hold when the benchmark (QQQ) is in an uptrend.
  - 무미래참조: signal = rebalance-day close, fill = next session open.
"""

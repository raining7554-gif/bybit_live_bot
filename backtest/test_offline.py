"""Offline self-test: synthetic OHLCV with regime switches.

Verifies engine + indicators + strategies run end-to-end without real data.
Run: python -m backtest.test_offline
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from .indicators import add_all_15m, add_basic_1h, add_basic_4h, sma, resample_to
from .engine import run_backtest, BTConfig
from .metrics import compute_metrics, format_report
from .strategies.v63d import make_strategy as make_v63d
from .strategies.strategy_a import make_strategy as make_a
from .strategies.strategy_c import make_strategy as make_c


def synth_ohlcv(n_bars: int = 4 * 24 * 30, freq_min: int = 15, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # 3-regime synthetic: trend up, sideways, trend down
    seg = n_bars // 3
    drifts = np.concatenate([
        np.full(seg, 0.0008),     # trend up
        np.full(seg, 0.0),        # sideways
        np.full(n_bars - 2 * seg, -0.0008),  # trend down
    ])
    vols = np.concatenate([
        np.full(seg, 0.003),
        np.full(seg, 0.001),
        np.full(n_bars - 2 * seg, 0.0035),
    ])
    rets = rng.normal(drifts, vols)
    price = 50000.0 * np.exp(np.cumsum(rets))
    # Build OHLCV with intra-bar noise
    high_noise = np.abs(rng.normal(0, vols)) * price
    low_noise = np.abs(rng.normal(0, vols)) * price
    op = np.concatenate([[50000.0], price[:-1]])
    hi = np.maximum(op, price) + high_noise
    lo = np.minimum(op, price) - low_noise
    vol = rng.lognormal(8, 0.3, n_bars)
    idx = pd.date_range("2025-01-01", periods=n_bars, freq=f"{freq_min}min", tz="UTC")
    df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": price, "volume": vol}, index=idx)
    df.index.name = "dt"
    return df


def main():
    print("== synth data ==")
    df_15m_raw = synth_ohlcv(n_bars=4 * 24 * 60, freq_min=15)  # 60 days of 15m
    print(f"  15m bars: {len(df_15m_raw)}  range: {df_15m_raw.index[0]} → {df_15m_raw.index[-1]}")

    df_15m = add_all_15m(df_15m_raw)
    print(f"  ATR mean: {df_15m['atr'].mean():.2f}  ADX max: {df_15m['adx'].max():.2f}")

    # Resample to 1h, 4h, 1d
    df_1h_raw = resample_to(df_15m_raw, "60min")
    df_4h_raw = resample_to(df_15m_raw, "240min")
    df_1d_raw = resample_to(df_15m_raw, "1D")
    print(f"  1h bars: {len(df_1h_raw)} | 4h bars: {len(df_4h_raw)} | 1d bars: {len(df_1d_raw)}")

    df_1h = add_basic_1h(df_1h_raw)
    df_4h = add_basic_4h(df_4h_raw)
    df_1d = df_1d_raw.copy()
    df_1d["ema50"] = sma(df_1d["close"], 50)
    df_1d["ema50_prev5"] = df_1d["ema50"].shift(5)

    cfg_v63d = BTConfig(initial_equity=1000.0, max_leverage=7.0, use_risk_sizing=False)
    cfg_risk = BTConfig(initial_equity=1000.0, max_leverage=5.0, use_risk_sizing=True, risk_per_trade=0.01)
    cfg_risk_half = BTConfig(initial_equity=1000.0, max_leverage=3.0, use_risk_sizing=True, risk_per_trade=0.005)

    print("\n== running v6.3d ==")
    res_v = run_backtest(df_15m, make_v63d(), cfg=cfg_v63d, df_1h=df_1h, df_4h=df_4h, df_1d=df_1d, warmup=300)
    m_v = compute_metrics(res_v, "v6.3d")
    print(f"  trades: {m_v.get('n_trades')}  final: ${m_v['final_equity']:.2f}")

    print("\n== running A ==")
    res_a = run_backtest(df_15m, make_a(), cfg=cfg_risk, df_1h=df_1h, df_4h=df_4h, df_1d=df_1d, warmup=300)
    m_a = compute_metrics(res_a, "A")
    print(f"  trades: {m_a.get('n_trades')}  final: ${m_a['final_equity']:.2f}")

    print("\n== running C ==")
    res_c = run_backtest(df_15m, make_c(), cfg=cfg_risk_half, df_1h=df_1h, df_4h=df_4h, df_1d=df_1d, warmup=300)
    m_c = compute_metrics(res_c, "C")
    print(f"  trades: {m_c.get('n_trades')}  final: ${m_c['final_equity']:.2f}")

    print("\n" + format_report([m_v, m_a, m_c]))
    print("\n== self-test PASS (no exceptions) ==")


if __name__ == "__main__":
    main()

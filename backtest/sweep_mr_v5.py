"""Sweep MR v5 parameters and rank by Sharpe / total return.

매주 GitHub Actions cron 으로 자동 실행 → 결과 JSON 커밋.
실제 적용은 사람이 코드/config 수정 (자동 적용 X).

Sweeps:
  - SCORE_MIN: 45, 50, 55
  - RSI_OVERSOLD: 30, 35, 40 (mirror RSI_OVERBOUGHT 70/65/60)
  - BB_POS_LOW: 0.10, 0.15, 0.20 (mirror BB_POS_HIGH)
  - VOL_SPIKE_MIN: 1.2, 1.5, 1.8

Usage:
    python -m backtest.sweep_mr_v5 --days 180 --symbol BTCUSDT
    python -m backtest.sweep_mr_v5 --out reports/sweep_mr.json
"""
from __future__ import annotations
import argparse
import itertools
import json
import os
import sys
import time
from datetime import datetime

import pandas as pd

from .data import load_kline
from .indicators import add_all_15m, add_basic_1h, add_basic_4h
from .engine import run_backtest, BTConfig
from .metrics import compute_metrics
from .strategies import strategy_mr_v5 as smr


REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def _make_mr_strat():
    """MR v5 strategy callable for engine.run_backtest."""
    state = {"last_loss_idx": -10_000, "last_win_idx": -10_000}

    def strat(ctx):
        i = ctx["i"]
        df = ctx["df_15m"]
        h4 = ctx["df_4h"]
        pos = ctx["position"]
        row = df.iloc[i]
        row_h4 = h4.iloc[i] if h4 is not None else None

        if pos is not None:
            return None

        if i - state["last_loss_idx"] < smr.COOLDOWN_BARS_LOSS:
            return None
        if i - state["last_win_idx"] < smr.COOLDOWN_BARS_WIN:
            return None

        side, reason, score = smr._check_signal_v5(row, row_h4)
        if side == "none":
            return None
        atr15 = row.atr
        if pd.isna(atr15) or atr15 <= 0:
            return None

        if side == "long":
            stop = row.close - smr.ATR_STOP_MULT * atr15
            tp = row.bb_mid
            if tp <= row.close:
                return None
        else:
            stop = row.close + smr.ATR_STOP_MULT * atr15
            tp = row.bb_mid
            if tp >= row.close:
                return None

        return {
            "action": "open", "side": side,
            "stop": float(stop), "tp": float(tp),
            "size_pct": 0.20, "leverage": 5.0,
            "tag": f"MR_v5_{score:.0f}",
        }

    return strat


def _apply_params(p: dict):
    """Monkey-patch MR v5 module constants for one sweep iteration."""
    smr.SCORE_MIN = p["score_min"]
    smr.RSI_OVERSOLD = p["rsi_oversold"]
    smr.RSI_OVERBOUGHT = 100.0 - p["rsi_oversold"]
    smr.BB_POS_LOW = p["bb_low"]
    smr.BB_POS_HIGH = 1.0 - p["bb_low"]
    smr.VOL_SPIKE_MIN = p["vol_spike"]


def run_sweep(symbol: str, days: int, out_path: str):
    print(f"[sweep] {symbol} {days}d — loading data ...")
    df15_raw = load_kline(symbol, "15", days=days)
    df1h_raw = load_kline(symbol, "60", days=days)
    df4h_raw = load_kline(symbol, "240", days=days)
    if any(len(d) == 0 for d in [df15_raw, df1h_raw, df4h_raw]):
        raise RuntimeError("empty data — API blocked or cache missing")

    df15 = add_all_15m(df15_raw)
    df1h = add_basic_1h(df1h_raw)
    df4h = add_basic_4h(df4h_raw)

    grid = {
        "score_min":     [45.0, 50.0, 55.0],
        "rsi_oversold":  [30.0, 35.0, 40.0],
        "bb_low":        [0.10, 0.15, 0.20],
        "vol_spike":     [1.2, 1.5, 1.8],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"[sweep] {len(combos)} param combinations")

    cfg = BTConfig(initial_equity=1000.0, max_leverage=5.0)
    results = []

    t0 = time.time()
    for idx, vals in enumerate(combos, 1):
        params = dict(zip(keys, vals))
        _apply_params(params)
        try:
            res = run_backtest(df15, _make_mr_strat(), cfg=cfg,
                               df_1h=df1h, df_4h=df4h, warmup=300)
            m = compute_metrics(res, name=f"sweep_{idx}")
            results.append({
                "params":      params,
                "n_trades":    m.get("n_trades", 0),
                "win_rate":    round(m.get("win_rate", 0) * 100, 1),
                "total_pct":   round(m.get("total_return_pct", 0), 2),
                "sharpe":      round(m.get("sharpe", 0), 2),
                "mdd_pct":     round(m.get("mdd_pct", 0), 2),
                "final_eq":    round(m.get("final_equity", 0), 2),
            })
            if idx % 10 == 0:
                el = time.time() - t0
                print(f"[sweep] {idx}/{len(combos)} ({el:.0f}s)")
        except Exception as e:
            print(f"[sweep] iter {idx} err: {e}")
            results.append({"params": params, "error": str(e)})

    # Sort by Sharpe (desc), then total return (desc)
    results.sort(key=lambda r: (r.get("sharpe", -99), r.get("total_pct", -99)),
                 reverse=True)

    output = {
        "ts":         datetime.utcnow().isoformat() + "Z",
        "symbol":     symbol,
        "days":       days,
        "n_combos":   len(combos),
        "top10":      results[:10],
        "current": {
            "score_min": 50.0, "rsi_oversold": 35.0,
            "bb_low": 0.15, "vol_spike": 1.5,
        },
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[sweep] saved → {out_path}")

    # Print top 5 to console
    print("\n=== TOP 5 (by Sharpe) ===")
    for i, r in enumerate(results[:5], 1):
        if "error" in r:
            continue
        print(f"#{i} sharpe={r['sharpe']} ret={r['total_pct']}% "
              f"trades={r['n_trades']} wr={r['win_rate']}% mdd={r['mdd_pct']}%")
        print(f"   {r['params']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--out", default=os.path.join(REPORT_DIR, "sweep_mr_v5.json"))
    args = ap.parse_args()
    run_sweep(args.symbol, args.days, args.out)


if __name__ == "__main__":
    main()

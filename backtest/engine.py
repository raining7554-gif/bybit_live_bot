"""Bar-by-bar backtest engine with realistic fees, slippage, leverage.

Strategy interface:
    StrategyProtocol(ctx) -> dict | None
        ctx: { i, df_15m, df_1h, df_4h, df_1d, position, equity, ... }
        returns:
            {"action": "open", "side": "long"|"short", "size_pct": 0..1,
             "stop": float, "tp": float|None, "tag": str}
            or {"action": "close", "reason": str}
            or {"action": "modify_stop", "stop": float}
            or None  (do nothing)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import math
import numpy as np
import pandas as pd


@dataclass
class Trade:
    entry_dt: pd.Timestamp
    exit_dt: pd.Timestamp
    side: str
    entry: float
    exit: float
    size: float
    leverage: float
    pnl: float
    pnl_pct: float
    fees: float
    reason: str
    tag: str
    bars: int


@dataclass
class Position:
    side: str
    entry: float
    size: float
    leverage: float
    stop: float
    tp: Optional[float]
    peak: float = 0.0
    entry_idx: int = 0
    entry_dt: pd.Timestamp = None
    tag: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class BTConfig:
    initial_equity: float = 1000.0
    taker_fee: float = 0.00055   # Bybit perp taker
    slippage: float = 0.0003     # 0.03% one-side slippage estimate
    max_leverage: float = 5.0
    risk_per_trade: float = 0.01  # 1% of equity at stop distance
    use_risk_sizing: bool = True  # if False, falls back to size_pct * equity * leverage


def _hit(low: float, high: float, level: float) -> bool:
    return low <= level <= high


def run_backtest(
    df_15m: pd.DataFrame,
    strategy: Callable,
    cfg: BTConfig = BTConfig(),
    df_1h: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    df_1d: Optional[pd.DataFrame] = None,
    warmup: int = 250,
) -> dict:
    """Run a strategy. df_15m is master timeline; HTF DFs aligned by reindex+ffill."""
    df = df_15m
    # Align HTFs to 15m timeline (ffill). Assumes UTC index.
    def align(htf):
        if htf is None: return None
        return htf.reindex(df.index, method="ffill")
    h1 = align(df_1h)
    h4 = align(df_4h)
    d1 = align(df_1d)

    equity = cfg.initial_equity
    pos: Optional[Position] = None
    trades: list[Trade] = []
    equity_curve = np.zeros(len(df))
    in_pos_curve = np.zeros(len(df), dtype=bool)

    # Precompute arrays for speed
    open_ = df["open"].values
    high_ = df["high"].values
    low_ = df["low"].values
    close_ = df["close"].values
    idx_ = df.index

    for i in range(len(df)):
        equity_curve[i] = equity
        if i < warmup:
            continue

        # Mark-to-market for in-position equity tracking
        if pos:
            in_pos_curve[i] = True
            o, h, l, c = open_[i], high_[i], low_[i], close_[i]
            # Update peak
            if pos.side == "long":
                pnl_pct = (h - pos.entry) / pos.entry
            else:
                pnl_pct = (pos.entry - l) / pos.entry
            if pnl_pct > pos.peak:
                pos.peak = pnl_pct

            # Stop / TP intra-bar (conservative: stop checked first)
            close_signal = None
            exit_price = None
            if pos.side == "long":
                if l <= pos.stop:
                    close_signal = "sl"
                    exit_price = min(o, pos.stop)
                elif pos.tp is not None and h >= pos.tp:
                    close_signal = "tp"
                    exit_price = max(o, pos.tp)
            else:
                if h >= pos.stop:
                    close_signal = "sl"
                    exit_price = max(o, pos.stop)
                elif pos.tp is not None and l <= pos.tp:
                    close_signal = "tp"
                    exit_price = min(o, pos.tp)

            if close_signal:
                exit_price = exit_price * (1 - cfg.slippage if pos.side == "long" else 1 + cfg.slippage)
                if pos.side == "long":
                    raw_pct = (exit_price - pos.entry) / pos.entry
                else:
                    raw_pct = (pos.entry - exit_price) / pos.entry
                notional = pos.size * pos.entry
                pnl = notional * raw_pct
                fees = notional * cfg.taker_fee + (pos.size * exit_price) * cfg.taker_fee
                pnl -= fees
                equity += pnl
                trades.append(Trade(
                    entry_dt=pos.entry_dt, exit_dt=idx_[i], side=pos.side,
                    entry=pos.entry, exit=exit_price, size=pos.size,
                    leverage=pos.leverage, pnl=pnl, pnl_pct=raw_pct - 2 * cfg.taker_fee,
                    fees=fees, reason=close_signal, tag=pos.tag, bars=i - pos.entry_idx
                ))
                pos = None
                continue

        # Strategy decision
        ctx = {
            "i": i, "dt": idx_[i],
            "df_15m": df, "df_1h": h1, "df_4h": h4, "df_1d": d1,
            "position": pos, "equity": equity, "cfg": cfg,
            "open": open_[i], "high": high_[i], "low": low_[i], "close": close_[i],
        }
        sig = strategy(ctx)
        if sig is None:
            continue

        action = sig.get("action")
        if action == "open" and pos is None:
            side = sig["side"]
            stop = float(sig["stop"])
            tp = float(sig["tp"]) if sig.get("tp") is not None else None
            entry_price = close_[i] * (1 + cfg.slippage if side == "long" else 1 - cfg.slippage)
            stop_dist = abs(entry_price - stop) / entry_price
            if stop_dist <= 0:
                continue

            if cfg.use_risk_sizing:
                risk_dollars = equity * cfg.risk_per_trade
                notional = risk_dollars / stop_dist
                max_notional = equity * cfg.max_leverage
                notional = min(notional, max_notional)
            else:
                size_pct = float(sig.get("size_pct", 0.1))
                notional = equity * size_pct * cfg.max_leverage

            size = notional / entry_price
            if notional < 5:
                continue
            leverage_used = notional / equity
            pos = Position(
                side=side, entry=entry_price, size=size,
                leverage=leverage_used, stop=stop, tp=tp,
                entry_idx=i, entry_dt=idx_[i], tag=sig.get("tag", ""),
                extras=sig.get("extras", {})
            )
        elif action == "close" and pos is not None:
            exit_price = close_[i] * (1 - cfg.slippage if pos.side == "long" else 1 + cfg.slippage)
            if pos.side == "long":
                raw_pct = (exit_price - pos.entry) / pos.entry
            else:
                raw_pct = (pos.entry - exit_price) / pos.entry
            notional = pos.size * pos.entry
            pnl = notional * raw_pct
            fees = notional * cfg.taker_fee + (pos.size * exit_price) * cfg.taker_fee
            pnl -= fees
            equity += pnl
            trades.append(Trade(
                entry_dt=pos.entry_dt, exit_dt=idx_[i], side=pos.side,
                entry=pos.entry, exit=exit_price, size=pos.size,
                leverage=pos.leverage, pnl=pnl, pnl_pct=raw_pct - 2 * cfg.taker_fee,
                fees=fees, reason=sig.get("reason", "manual"),
                tag=pos.tag, bars=i - pos.entry_idx
            ))
            pos = None
        elif action == "modify_stop" and pos is not None:
            new_stop = float(sig["stop"])
            if pos.side == "long" and new_stop > pos.stop:
                pos.stop = new_stop
            elif pos.side == "short" and new_stop < pos.stop:
                pos.stop = new_stop

    return {
        "trades": trades,
        "equity_curve": pd.Series(equity_curve, index=df.index),
        "in_position": pd.Series(in_pos_curve, index=df.index),
        "final_equity": equity,
    }
